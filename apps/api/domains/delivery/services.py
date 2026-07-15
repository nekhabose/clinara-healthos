"""Delivery service interface (spec §7.4, plan Phase 3 workstream 4).

The single entry point for EHR write-back and patient-portal messaging. Two guarantees:

  * **Idempotent write-back** — ``queue_write_back`` is keyed by an idempotency key derived
    from the workflow + channel, so a duplicate approved event never creates a second task
    or portal message (spec §6.7.6; plan Phase 3 exit gate).
  * **Confirmed delivery** — ``deliver`` records a ``DeliveryAttempt`` and emits
    ``DeliverySucceeded`` / ``DeliveryFailed`` so an operator always knows the outcome.

The physical send goes through an injectable ``EhrClient`` (default: an in-proc stub that
confirms). Real adapters (SMART write-back, portal APIs) implement the same protocol without
touching this governance code.
"""
from __future__ import annotations

import hashlib
import uuid
from typing import Any, Protocol

from clinara_shared_types import EventType
from django.db import transaction

from clinara.middleware.phi_safe_logging import correlation_id as _correlation_id
from clinara.middleware.tenant import current_tenant_id, set_db_tenant
from core.outbox import publish_event
from domains.audit import services as audit

from .models import (
    DeliveryAttempt,
    OutboundChannel,
    OutboundMessage,
    OutboundStatus,
)


class DeliveryError(RuntimeError):
    pass


class EhrClient(Protocol):
    def send(self, *, channel: str, target: str, subject: str, body: str) -> str:
        """Send and return an external id, or raise to signal failure."""
        ...


class _StubEhrClient:
    """Deterministic in-proc client — confirms delivery and returns a stable external id."""

    def send(self, *, channel: str, target: str, subject: str, body: str) -> str:
        digest = hashlib.sha256(f"{channel}:{target}:{subject}".encode()).hexdigest()[:16]
        return f"ehr-{digest}"


def _bind(tenant_id: str) -> None:
    current_tenant_id.set(str(tenant_id))
    _correlation_id.set(str(uuid.uuid4()))
    set_db_tenant(str(tenant_id))


def _idempotency_key(tenant_id: str, workflow_id: str, channel: str) -> str:
    material = f"{tenant_id}:{workflow_id}:{channel}"
    return "out:" + hashlib.sha256(material.encode()).hexdigest()[:40]


def queue_write_back(
    *, tenant_id: str, workflow_id: str, channel: str, target: str,
    subject: str = "", body: str = "", actor: str = "system",
) -> tuple[OutboundMessage, bool]:
    """Idempotently create an outbound message for an approved workflow. Returns (msg, created)."""
    if channel not in OutboundChannel.values:
        raise ValueError(f"unknown channel {channel!r}")
    _bind(tenant_id)
    key = _idempotency_key(tenant_id, workflow_id, channel)
    with transaction.atomic():
        message, created = OutboundMessage.objects.get_or_create(
            idempotency_key=key,
            defaults={
                "tenant_id": tenant_id, "channel": channel, "workflow_id": workflow_id,
                "target": target, "subject": subject, "body": body,
                "status": OutboundStatus.PENDING,
            },
        )
        if created:
            audit.record(actor=actor, action="write_back_queued",
                         resource=f"outbound:{message.id}", reason=channel,
                         after_state={"channel": channel, "workflow_id": workflow_id})
    return message, created


def deliver(*, tenant_id: str, message_id: str, client: EhrClient | None = None,
            actor: str = "system") -> OutboundMessage:
    """Attempt delivery, record the attempt, and emit a Succeeded/Failed event.

    Already-delivered messages are a no-op (idempotent) — a retry never double-sends.
    """
    client = client or _StubEhrClient()
    _bind(tenant_id)
    with transaction.atomic():
        message = OutboundMessage.objects.select_for_update().get(
            id=message_id, tenant_id=tenant_id
        )
        if message.status == OutboundStatus.DELIVERED:
            return message  # confirmed already — never double-deliver

        try:
            external_id = client.send(
                channel=message.channel, target=message.target,
                subject=message.subject, body=message.body,
            )
        except Exception as exc:  # delivery failure is data, never a silent drop
            DeliveryAttempt.objects.create(
                tenant_id=tenant_id, message=message, succeeded=False, detail=str(exc)[:255]
            )
            message.status = OutboundStatus.FAILED
            message.save(update_fields=["status", "updated_at"])
            audit.record(actor=actor, action="delivery_failed",
                         resource=f"outbound:{message.id}", reason=str(exc)[:120])
            publish_event(
                event_type=EventType.DELIVERY_FAILED.value,
                idempotency_key=f"{message.id}:failed:{uuid.uuid4()}",
                payload={"message_id": str(message.id), "channel": message.channel},
            )
            return message

        DeliveryAttempt.objects.create(
            tenant_id=tenant_id, message=message, succeeded=True, detail=external_id
        )
        message.status = OutboundStatus.DELIVERED
        message.external_id = external_id
        message.save(update_fields=["status", "external_id", "updated_at"])
        audit.record(actor=actor, action="delivery_succeeded",
                     resource=f"outbound:{message.id}", reason=message.channel,
                     after_state={"external_id": external_id})
        publish_event(
            event_type=EventType.DELIVERY_SUCCEEDED.value,
            idempotency_key=f"{message.id}:delivered",
            payload={"message_id": str(message.id), "channel": message.channel,
                     "external_id": external_id},
        )
    return message


def failure_rate(tenant_id: str) -> dict[str, Any]:
    """Delivery health snapshot for the ops dashboard (spec §12.3)."""
    _bind(tenant_id)
    total = OutboundMessage.objects.filter(tenant_id=tenant_id).count()
    failed = OutboundMessage.objects.filter(
        tenant_id=tenant_id, status=OutboundStatus.FAILED
    ).count()
    delivered = OutboundMessage.objects.filter(
        tenant_id=tenant_id, status=OutboundStatus.DELIVERED
    ).count()
    return {"total": total, "delivered": delivered, "failed": failed,
            "failure_rate": round(failed / total, 4) if total else 0.0}


__all__ = [
    "queue_write_back", "deliver", "failure_rate", "EhrClient", "DeliveryError",
    "OutboundChannel",
]
