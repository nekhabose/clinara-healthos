"""Delivery service interface (spec §7.4, plan Phase 3 workstream 4; Phase 7 write-back).

The single entry point for EHR write-back and patient-portal messaging. Guarantees:

  * **Idempotent write-back** — ``queue_write_back`` is keyed by an idempotency key derived
    from the workflow + channel, so a duplicate approved event never creates a second task
    or portal message (spec §6.7.6; plan Phase 3 exit gate).
  * **Confirmed delivery with bounded retry** — ``deliver`` retries *transient* failures
    (429/5xx/network) with backoff, records every ``DeliveryAttempt``, and emits
    ``DeliverySucceeded`` / ``DeliveryFailed`` so an operator always knows the outcome
    (Phase 7).
  * **Direct release** — ``release_result`` produces exactly one patient-portal message and
    one EHR-task per approved workflow and delivers both; re-releasing is a no-op (Phase 7).
  * **Degraded-channel alert** — a write-back failure spike raises a ``WriteBackDegraded``
    operator signal, never a silent drop (Phase 7).

The physical send goes through an injectable ``EhrClient`` (default: an in-proc stub that
confirms). The real adapter (``domains.delivery.adapters.SmartEhrClient``, SMART-on-FHIR
write-back) implements the same protocol without touching this governance code. A failure
carrying a truthy ``retryable`` attribute is retried; anything else fails fast.
"""
from __future__ import annotations

import hashlib
import time
import uuid
from collections.abc import Callable
from typing import Any, Protocol

from clinara_integration_sdk import RetryPolicy
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

# A write-back channel is "degraded" once at least this many sends have failed and the
# failure rate is at or above this fraction — the point at which an operator should look.
_DEGRADED_MIN_FAILURES = 3
_DEGRADED_FAILURE_RATE = 0.5


class DeliveryError(RuntimeError):
    pass


class EhrClient(Protocol):
    def send(self, *, channel: str, target: str, subject: str, body: str) -> str:
        """Send and return an external id, or raise to signal failure. A raised exception with
        a truthy ``retryable`` attribute is treated as transient and retried."""
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
            actor: str = "system", retry_policy: RetryPolicy | None = None,
            sleeper: Callable[[float], None] = time.sleep) -> OutboundMessage:
    """Attempt delivery with bounded retry, record each attempt, and emit Succeeded/Failed.

    Already-delivered messages are a no-op (idempotent) — a retry never double-sends. A send
    that raises with a truthy ``retryable`` attribute (transient 429/5xx/network) is retried
    with backoff up to ``retry_policy.max_attempts``; a terminal failure fails fast. Either
    way every attempt is recorded and the terminal outcome emits an event — zero silent loss.

    ``sleeper`` is injected so tests are instant and the backoff schedule is deterministic.
    """
    client = client or _StubEhrClient()
    policy = retry_policy or RetryPolicy()
    _bind(tenant_id)
    with transaction.atomic():
        message = OutboundMessage.objects.select_for_update().get(
            id=message_id, tenant_id=tenant_id
        )
        if message.status == OutboundStatus.DELIVERED:
            return message  # confirmed already — never double-deliver

        attempt = 0
        while True:
            attempt += 1
            delay = policy.backoff(attempt)
            if delay:
                sleeper(delay)
            try:
                external_id = client.send(
                    channel=message.channel, target=message.target,
                    subject=message.subject, body=message.body,
                )
            except Exception as exc:  # delivery failure is data, never a silent drop
                DeliveryAttempt.objects.create(
                    tenant_id=tenant_id, message=message, succeeded=False,
                    detail=str(exc)[:255],
                )
                retryable = bool(getattr(exc, "retryable", False))
                if policy.should_retry(attempt, retryable=retryable):
                    continue  # transient — back off and try again
                message.status = OutboundStatus.FAILED
                message.save(update_fields=["status", "updated_at"])
                audit.record(actor=actor, action="delivery_failed",
                             resource=f"outbound:{message.id}",
                             reason=f"{str(exc)[:110]} (attempts={attempt})")
                publish_event(
                    event_type=EventType.DELIVERY_FAILED.value,
                    idempotency_key=f"{message.id}:failed:{uuid.uuid4()}",
                    payload={"message_id": str(message.id), "channel": message.channel,
                             "attempts": attempt},
                )
                _flag_degraded_if_needed(tenant_id, message.channel)
                return message

            DeliveryAttempt.objects.create(
                tenant_id=tenant_id, message=message, succeeded=True, detail=external_id
            )
            message.status = OutboundStatus.DELIVERED
            message.external_id = external_id
            message.save(update_fields=["status", "external_id", "updated_at"])
            audit.record(actor=actor, action="delivery_succeeded",
                         resource=f"outbound:{message.id}", reason=message.channel,
                         after_state={"external_id": external_id, "attempts": attempt})
            publish_event(
                event_type=EventType.DELIVERY_SUCCEEDED.value,
                idempotency_key=f"{message.id}:delivered",
                payload={"message_id": str(message.id), "channel": message.channel,
                         "external_id": external_id, "attempts": attempt},
            )
            return message


def release_result(
    *, tenant_id: str, workflow_id: str, patient_target: str,
    care_team_target: str = "care_team", portal_subject: str = "", portal_body: str = "",
    task_note: str = "", actor: str = "system", client: EhrClient | None = None,
    deliver_now: bool = True, retry_policy: RetryPolicy | None = None,
    sleeper: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    """Release an approved result: exactly one patient-portal message + one EHR task.

    Both writes are idempotent per (workflow, channel), so re-releasing the same workflow
    never produces a second portal message or task (Phase 7 exit gate). When ``deliver_now``
    is set, both are delivered through the governed ``deliver`` path.
    """
    portal_msg, portal_created = queue_write_back(
        tenant_id=tenant_id, workflow_id=workflow_id, channel=OutboundChannel.PATIENT_PORTAL,
        target=patient_target, subject=portal_subject, body=portal_body, actor=actor,
    )
    task_msg, task_created = queue_write_back(
        tenant_id=tenant_id, workflow_id=workflow_id, channel=OutboundChannel.EHR_TASK,
        target=care_team_target, subject=portal_subject,
        body=task_note or "Result released to patient — review if needed.", actor=actor,
    )
    if deliver_now:
        portal_msg = deliver(tenant_id=tenant_id, message_id=str(portal_msg.id),
                             client=client, actor=actor, retry_policy=retry_policy,
                             sleeper=sleeper)
        task_msg = deliver(tenant_id=tenant_id, message_id=str(task_msg.id),
                           client=client, actor=actor, retry_policy=retry_policy,
                           sleeper=sleeper)

    _bind(tenant_id)
    with transaction.atomic():
        publish_event(
            event_type=EventType.RESULT_RELEASED.value,
            idempotency_key=f"released:{tenant_id}:{workflow_id}",
            payload={"workflow_id": str(workflow_id),
                     "portal_message_id": str(portal_msg.id),
                     "task_message_id": str(task_msg.id)},
        )
    return {
        "portal": {"id": str(portal_msg.id), "status": portal_msg.status,
                   "created": portal_created,
                   "external_id": portal_msg.external_id or None},
        "task": {"id": str(task_msg.id), "status": task_msg.status,
                 "created": task_created, "external_id": task_msg.external_id or None},
    }


def write_back_health(
    tenant_id: str, *, min_failures: int = _DEGRADED_MIN_FAILURES,
    failure_threshold: float = _DEGRADED_FAILURE_RATE, channel: str | None = None,
) -> dict[str, Any]:
    """Write-back health snapshot with a ``degraded`` verdict for the ops dashboard.

    ``degraded`` is True once failures reach ``min_failures`` and the failure rate is at or
    above ``failure_threshold`` — the operator-alert condition for a write-back spike.
    """
    _bind(tenant_id)
    qs = OutboundMessage.objects.filter(tenant_id=tenant_id)
    if channel is not None:
        qs = qs.filter(channel=channel)
    total = qs.count()
    failed = qs.filter(status=OutboundStatus.FAILED).count()
    delivered = qs.filter(status=OutboundStatus.DELIVERED).count()
    rate = round(failed / total, 4) if total else 0.0
    degraded = failed >= min_failures and rate >= failure_threshold
    return {"total": total, "delivered": delivered, "failed": failed,
            "failure_rate": rate, "degraded": degraded, "channel": channel}


def _flag_degraded_if_needed(tenant_id: str, channel: str) -> None:
    """Emit a ``WriteBackDegraded`` operator alert when the channel crosses the spike
    threshold. Called inside the failing ``deliver`` transaction; idempotency-keyed on the
    failure count so a given spike level alerts at most once."""
    health = write_back_health(tenant_id, channel=channel)
    if not health["degraded"]:
        return
    publish_event(
        event_type=EventType.WRITE_BACK_DEGRADED.value,
        idempotency_key=f"writeback-degraded:{tenant_id}:{channel}:{health['failed']}",
        payload={"channel": channel, "failed": health["failed"],
                 "failure_rate": health["failure_rate"]},
    )
    audit.record(actor="system", action="write_back_degraded",
                 resource=f"delivery:{channel}",
                 reason=f"failed={health['failed']} rate={health['failure_rate']}")


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
    "queue_write_back", "deliver", "release_result", "failure_rate", "write_back_health",
    "EhrClient", "DeliveryError", "OutboundChannel",
]
