"""Transactional outbox publisher.

Call ``publish_event`` from inside a domain service while holding a DB transaction that
also persists the state change. The event is durably queued in the same commit, so a
crash can never lose it (plan §1.2, spec §7.5).
"""
from __future__ import annotations

from typing import Any

from django.db import transaction

from clinara.middleware.phi_safe_logging import correlation_id
from clinara.middleware.tenant import current_tenant_id

from .models import DomainEventOutbox


def publish_event(
    *,
    event_type: str,
    idempotency_key: str,
    payload: dict[str, Any],
    schema_version: int = 1,
    causation_id: str | None = None,
    audit_metadata: dict[str, Any] | None = None,
) -> DomainEventOutbox:
    """Enqueue a domain event in the outbox within the current transaction.

    Duplicate ``idempotency_key`` values are ignored (get_or_create) so replays and
    at-least-once delivery never double-emit (spec §6.7.6).
    """
    if not transaction.get_connection().in_atomic_block:
        raise RuntimeError("publish_event must be called inside an atomic transaction")

    event, _created = DomainEventOutbox.objects.get_or_create(
        idempotency_key=idempotency_key,
        defaults={
            "event_type": event_type,
            "schema_version": schema_version,
            "tenant_id": current_tenant_id.get(),
            "correlation_id": correlation_id.get() or "",
            "causation_id": causation_id,
            "payload": payload,
            "audit_metadata": audit_metadata or {},
        },
    )
    return event
