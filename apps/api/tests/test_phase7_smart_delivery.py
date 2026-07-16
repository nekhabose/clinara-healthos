"""Phase 7 — Real EMR Connectivity: SMART write-back through the governed delivery path.

End-to-end proof that the real ``SmartEhrClient`` (SMART-on-FHIR write-back) delivers through
the existing delivery governance: confirmed success, bounded retry on transient failure with
zero silent loss, idempotent direct-release of exactly one portal message + one EHR task, a
degraded-channel operator alert on a write-back spike, and token reuse across deliveries.

Runs against a vendor-emulating fake transport (token endpoint + FHIR server) so the whole
flow is validated without a live EMR; production swaps the transport/signer by config.
"""
import json
import uuid

import pytest
from clinara_integration_sdk import HttpResponse, RetryPolicy

from core.models import DomainEventOutbox
from domains.delivery import services as delivery
from domains.delivery.adapters import build_smart_ehr_client, dev_signer
from domains.delivery.models import DeliveryAttempt, OutboundMessage, OutboundStatus

pytestmark = pytest.mark.django_db

TOKEN_URL = "https://ehr.example/oauth2/token"
BASE_URL = "https://fhir.example/api/FHIR/R4"
NO_SLEEP = lambda *_: None  # noqa: E731  (instant, deterministic backoff in tests)


def _tenant() -> str:
    return str(uuid.uuid4())


class FakeEhrTransport:
    """Emulates both the SMART token endpoint and the FHIR write endpoints."""

    def __init__(self):
        self.token_requests = 0
        self.fhir_requests = []
        self.fhir_status = {}  # resource_type -> status code to force

    def force(self, resource_type: str, status: int):
        self.fhir_status[resource_type] = status

    def request(self, req):
        if req.url == TOKEN_URL:
            self.token_requests += 1
            return HttpResponse(200, {}, json.dumps(
                {"access_token": f"tok-{self.token_requests}", "expires_in": 3600}).encode())
        # FHIR write
        self.fhir_requests.append(req)
        rtype = req.url.rstrip("/").split("/")[-1]
        status = self.fhir_status.get(rtype, 201)
        if status >= 400:
            return HttpResponse(status, {}, b'{"resourceType":"OperationOutcome"}')
        body = json.loads(req.body.decode())
        body["id"] = f"{rtype.lower()}-{len(self.fhir_requests)}"
        return HttpResponse(status, {"Content-Type": "application/fhir+json"},
                            json.dumps(body).encode())


def _client(transport, vendor="epic"):
    return build_smart_ehr_client(
        config={"base_url": BASE_URL, "token_url": TOKEN_URL, "client_id": "clinara",
                "scopes": ["system/Task.write", "system/Communication.write"], "vendor": vendor},
        signer=dev_signer(), transport=transport, clock=lambda: 1_700_000_000.0,
        jti_factory=lambda: "jti",
    )


def _queue(t, *, channel, target="P1", body="Your A1c is normal."):
    msg, _ = delivery.queue_write_back(
        tenant_id=t, workflow_id=str(uuid.uuid4()), channel=channel, target=target, body=body)
    return msg


# ---- SmartEhrClient channel mapping ----

def test_smart_client_maps_portal_to_communication_and_task_to_task():
    transport = FakeEhrTransport()
    client = _client(transport)
    comm_id = client.send(channel="patient_portal", target="P1", subject="Lab", body="normal")
    task_id = client.send(channel="ehr_task", target="care_team", subject="Lab", body="review")
    resource_types = [r.url.rsplit("/", 1)[-1] for r in transport.fhir_requests]
    assert resource_types == ["Communication", "Task"]
    assert comm_id.startswith("communication-")
    assert task_id.startswith("task-")


# ---- end-to-end through the governed deliver() ----

def test_deliver_via_smart_client_confirms_and_emits_event():
    t = _tenant()
    msg = _queue(t, channel="patient_portal")
    delivered = delivery.deliver(tenant_id=t, message_id=str(msg.id),
                                 client=_client(FakeEhrTransport()), sleeper=NO_SLEEP)
    assert delivered.status == OutboundStatus.DELIVERED
    assert delivered.external_id.startswith("communication-")
    assert DomainEventOutbox.objects.filter(
        tenant_id=t, event_type="DeliverySucceeded").exists()


def test_transient_failure_retries_then_fails_with_zero_silent_loss():
    t = _tenant()
    msg = _queue(t, channel="ehr_task", target="care_team")
    transport = FakeEhrTransport()
    transport.force("Task", 503)  # transient upstream error → retryable
    result = delivery.deliver(
        tenant_id=t, message_id=str(msg.id), client=_client(transport),
        retry_policy=RetryPolicy(max_attempts=3, base_delay_seconds=0.01), sleeper=NO_SLEEP)
    assert result.status == OutboundStatus.FAILED
    assert DeliveryAttempt.objects.filter(tenant_id=t, message=msg).count() == 3  # retried
    assert DomainEventOutbox.objects.filter(tenant_id=t, event_type="DeliveryFailed").exists()


def test_terminal_failure_does_not_retry():
    t = _tenant()
    msg = _queue(t, channel="ehr_task", target="care_team")
    transport = FakeEhrTransport()
    transport.force("Task", 400)  # bad request → terminal, must not retry
    result = delivery.deliver(
        tenant_id=t, message_id=str(msg.id), client=_client(transport),
        retry_policy=RetryPolicy(max_attempts=5), sleeper=NO_SLEEP)
    assert result.status == OutboundStatus.FAILED
    assert DeliveryAttempt.objects.filter(tenant_id=t, message=msg).count() == 1  # no retry


def test_retryable_failure_that_recovers_succeeds():
    t = _tenant()
    msg = _queue(t, channel="patient_portal")

    class Flaky:
        """Fails the first send, then recovers — proves retry reaches success."""
        def __init__(self):
            self.n = 0

        def send(self, **kw):
            self.n += 1
            if self.n == 1:
                from clinara_integration_sdk import FhirWriteError
                raise FhirWriteError("temporarily unavailable", status=503, retryable=True)
            return "communication-ok"

    result = delivery.deliver(tenant_id=t, message_id=str(msg.id), client=Flaky(),
                              retry_policy=RetryPolicy(max_attempts=3), sleeper=NO_SLEEP)
    assert result.status == OutboundStatus.DELIVERED
    assert result.external_id == "communication-ok"


# ---- direct release: exactly one portal message + one EHR task, idempotent ----

def test_release_result_produces_one_portal_and_one_task_idempotently():
    t = _tenant()
    wid = str(uuid.uuid4())
    first = delivery.release_result(
        tenant_id=t, workflow_id=wid, patient_target="P1",
        portal_body="Your result is ready.", client=_client(FakeEhrTransport()),
        sleeper=NO_SLEEP)
    assert first["portal"]["status"] == OutboundStatus.DELIVERED
    assert first["task"]["status"] == OutboundStatus.DELIVERED
    assert first["portal"]["created"] and first["task"]["created"]

    # Re-release the same workflow — no second portal message or task.
    second = delivery.release_result(
        tenant_id=t, workflow_id=wid, patient_target="P1",
        portal_body="Your result is ready.", client=_client(FakeEhrTransport()),
        sleeper=NO_SLEEP)
    assert not second["portal"]["created"] and not second["task"]["created"]
    assert OutboundMessage.objects.filter(tenant_id=t, channel="patient_portal").count() == 1
    assert OutboundMessage.objects.filter(tenant_id=t, channel="ehr_task").count() == 1
    assert DomainEventOutbox.objects.filter(tenant_id=t, event_type="ResultReleased").count() == 1


# ---- degraded-channel operator alert on a write-back spike ----

def test_write_back_spike_raises_degraded_alert():
    t = _tenant()
    transport = FakeEhrTransport()
    transport.force("Communication", 500)  # every portal write fails terminally? 500 is retryable
    # Use NO_RETRY so each message fails on a single attempt; three failures = a spike.
    from clinara_integration_sdk import NO_RETRY
    for _ in range(3):
        msg = _queue(t, channel="patient_portal")
        delivery.deliver(tenant_id=t, message_id=str(msg.id), client=_client(transport),
                         retry_policy=NO_RETRY, sleeper=NO_SLEEP)
    health = delivery.write_back_health(t, channel="patient_portal")
    assert health["degraded"] is True
    assert health["failed"] == 3
    assert DomainEventOutbox.objects.filter(
        tenant_id=t, event_type="WriteBackDegraded").exists()


def test_single_failure_is_not_degraded():
    t = _tenant()
    transport = FakeEhrTransport()
    transport.force("Communication", 400)
    msg = _queue(t, channel="patient_portal")
    delivery.deliver(tenant_id=t, message_id=str(msg.id), client=_client(transport),
                     sleeper=NO_SLEEP)
    assert delivery.write_back_health(t, channel="patient_portal")["degraded"] is False
    assert not DomainEventOutbox.objects.filter(
        tenant_id=t, event_type="WriteBackDegraded").exists()


# ---- token is fetched once and reused across deliveries ----

def test_token_is_reused_across_deliveries():
    t = _tenant()
    transport = FakeEhrTransport()
    client = _client(transport)  # one client → one cached token
    m1 = _queue(t, channel="patient_portal")
    m2 = _queue(t, channel="ehr_task", target="care_team")
    delivery.deliver(tenant_id=t, message_id=str(m1.id), client=client, sleeper=NO_SLEEP)
    delivery.deliver(tenant_id=t, message_id=str(m2.id), client=client, sleeper=NO_SLEEP)
    assert transport.token_requests == 1  # exactly one token round-trip for two writes
