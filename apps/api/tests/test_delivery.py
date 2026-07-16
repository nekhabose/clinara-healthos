"""EHR write-back & delivery (plan Phase 3, workstream 4 — idempotent, confirmed).

Proves a duplicate approved event never produces a second task/message, delivery is
confirmed with a Succeeded event, and a failing client produces a Failed event (never a
silent drop).
"""
import uuid

import pytest

from core.models import DomainEventOutbox
from domains.audit.models import AuditEvent
from domains.delivery import services as delivery
from domains.delivery.models import DeliveryAttempt, OutboundMessage

pytestmark = pytest.mark.django_db


def _tenant() -> str:
    return str(uuid.uuid4())


class _FailingClient:
    def send(self, *, channel, target, subject, body):
        raise RuntimeError("portal unreachable")


def test_write_back_is_idempotent_per_workflow_channel():
    t = _tenant()
    wid = str(uuid.uuid4())
    _, created1 = delivery.queue_write_back(
        tenant_id=t, workflow_id=wid, channel="ehr_task", target="care_team"
    )
    _, created2 = delivery.queue_write_back(
        tenant_id=t, workflow_id=wid, channel="ehr_task", target="care_team"
    )
    assert created1 is True
    assert created2 is False  # duplicate suppressed — no second task
    assert OutboundMessage.objects.filter(tenant_id=t).count() == 1


def test_deliver_confirms_and_emits_event():
    t = _tenant()
    wid = str(uuid.uuid4())
    message, _ = delivery.queue_write_back(
        tenant_id=t, workflow_id=wid, channel="patient_portal", target="P1",
        body="Your result is ready.",
    )
    delivered = delivery.deliver(tenant_id=t, message_id=str(message.id))
    assert delivered.status == "delivered"
    assert delivered.external_id
    assert DomainEventOutbox.objects.filter(
        tenant_id=t, event_type="DeliverySucceeded"
    ).exists()
    assert AuditEvent.objects.filter(tenant_id=t, action="delivery_succeeded").exists()


def test_deliver_is_idempotent_no_double_send():
    t = _tenant()
    wid = str(uuid.uuid4())
    message, _ = delivery.queue_write_back(
        tenant_id=t, workflow_id=wid, channel="ehr_task", target="care_team"
    )
    delivery.deliver(tenant_id=t, message_id=str(message.id))
    delivery.deliver(tenant_id=t, message_id=str(message.id))  # retry
    assert DeliveryAttempt.objects.filter(tenant_id=t, message=message).count() == 1


def test_delivery_failure_emits_failed_event():
    t = _tenant()
    wid = str(uuid.uuid4())
    message, _ = delivery.queue_write_back(
        tenant_id=t, workflow_id=wid, channel="patient_portal", target="P1"
    )
    result = delivery.deliver(tenant_id=t, message_id=str(message.id), client=_FailingClient())
    assert result.status == "failed"
    assert DomainEventOutbox.objects.filter(tenant_id=t, event_type="DeliveryFailed").exists()
    snapshot = delivery.failure_rate(t)
    assert snapshot["failed"] == 1
