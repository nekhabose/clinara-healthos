"""FHIR R4 write-back client (plan Phase 7 — closes G3).

Proves Task/Communication writes hit the right FHIR endpoints with a Bearer token, extract
the external id from either the body or the Location header, apply vendor profiles, and
classify HTTP failures as retryable (429/5xx/network) vs terminal (4xx) — all against a fake
FHIR server, no live EMR.
"""
import json

import pytest
from clinara_integration_sdk import (
    ATHENA,
    EPIC,
    FhirWriteBackClient,
    FhirWriteError,
    HmacSigner,
    HttpResponse,
    SmartBackendAuth,
    SmartConfig,
)
from clinara_integration_sdk.transport import TransportError

BASE = "https://fhir.example/api/FHIR/R4"


def _clock():
    return 1_700_000_000.0


class FakeTokenServer:
    def request(self, req):
        return HttpResponse(200, {}, json.dumps(
            {"access_token": "tok", "expires_in": 300}).encode())


def _auth():
    cfg = SmartConfig(client_id="c", token_url="https://ehr/token", scopes=("system/*.write",))
    return SmartBackendAuth(cfg, HmacSigner(b"s"), FakeTokenServer(), jti_factory=lambda: "j")


class FakeFhirServer:
    """Records write requests and returns a scripted response per resource type."""

    def __init__(self):
        self.requests = []
        self.responses = {}  # resource_type -> HttpResponse

    def set(self, resource_type, resp):
        self.responses[resource_type] = resp

    def request(self, req):
        self.requests.append(req)
        rtype = req.url.rstrip("/").split("/")[-1]
        if rtype in self.responses:
            return self.responses[rtype]
        # default: created, id echoed in body
        body = json.loads(req.body.decode())
        body["id"] = f"{rtype.lower()}-123"
        return HttpResponse(201, {"Content-Type": "application/fhir+json"},
                            json.dumps(body).encode())


def _client(server, profile=EPIC):
    return FhirWriteBackClient(
        base_url=BASE, auth=_auth(), transport=server, clock=_clock, profile=profile
    )


def test_create_task_posts_fhir_task_with_bearer_and_returns_id():
    server = FakeFhirServer()
    result = _client(server).create_task(patient_ref="P1", note="Review A1c result")
    req = server.requests[-1]
    assert req.url == f"{BASE}/Task"
    assert req.headers["Authorization"] == "Bearer tok"
    assert req.headers["Content-Type"] == "application/fhir+json"
    sent = json.loads(req.body.decode())
    assert sent["resourceType"] == "Task"
    assert sent["for"]["reference"] == "Patient/P1"
    assert result.external_id == "task-123"
    assert result.resource_type == "Task"


def test_create_communication_posts_fhir_communication():
    server = FakeFhirServer()
    result = _client(server).create_communication(
        patient_ref="Patient/P9", body="Your result is normal.", subject="Lab result"
    )
    req = server.requests[-1]
    assert req.url == f"{BASE}/Communication"
    sent = json.loads(req.body.decode())
    assert sent["resourceType"] == "Communication"
    assert sent["subject"]["reference"] == "Patient/P9"
    assert "Your result is normal." in sent["payload"][0]["contentString"]
    assert result.external_id == "communication-123"


def test_id_extracted_from_location_header_when_body_has_none():
    server = FakeFhirServer()
    server.set("Task", HttpResponse(
        201, {"Location": f"{BASE}/Task/abc-999/_history/1"}, b""))
    result = _client(server).create_task(patient_ref="P1", note="n")
    assert result.external_id == "abc-999"
    assert result.location.endswith("/_history/1")


def test_athena_profile_adds_communication_category():
    server = FakeFhirServer()
    _client(server, profile=ATHENA).create_communication(patient_ref="P1", body="hi")
    sent = json.loads(server.requests[-1].body.decode())
    assert sent["category"][0]["coding"][0]["code"] == "notification"
    # Epic profile does not add it.
    server2 = FakeFhirServer()
    _client(server2, profile=EPIC).create_communication(patient_ref="P1", body="hi")
    assert "category" not in json.loads(server2.requests[-1].body.decode())


def test_server_error_is_retryable():
    server = FakeFhirServer()
    server.set("Task", HttpResponse(503, {}, b"upstream unavailable"))
    with pytest.raises(FhirWriteError) as exc:
        _client(server).create_task(patient_ref="P1", note="n")
    assert exc.value.retryable is True
    assert exc.value.status == 503


def test_rate_limit_is_retryable():
    server = FakeFhirServer()
    server.set("Communication", HttpResponse(429, {}, b"slow down"))
    with pytest.raises(FhirWriteError) as exc:
        _client(server).create_communication(patient_ref="P1", body="b")
    assert exc.value.retryable is True


def test_client_error_is_terminal():
    server = FakeFhirServer()
    server.set("Task", HttpResponse(400, {}, b"bad reference"))
    with pytest.raises(FhirWriteError) as exc:
        _client(server).create_task(patient_ref="P1", note="n")
    assert exc.value.retryable is False
    assert exc.value.status == 400


def test_network_failure_is_retryable():
    class Broken:
        def request(self, req):
            raise TransportError("connection reset")

    client = FhirWriteBackClient(
        base_url=BASE, auth=_auth(), transport=Broken(), clock=_clock
    )
    with pytest.raises(FhirWriteError) as exc:
        client.create_task(patient_ref="P1", note="n")
    assert exc.value.retryable is True
