"""Integration monitoring (plan Phase 3, workstream 6 — spec §6.7.5, §12.3).

Turns raw gateway activity into the operator-facing signals that make "zero silent
failures" observable:

  * ``integration_health`` — per-interface connection status, throughput, and the full
    error/dead-letter/duplicate counters (spec §6.7.5).
  * ``scan_silent_gaps`` — detects the *absence* of expected traffic (heartbeat past its
    grace window) and raises a critical alert (plan Phase 3 key decision). This catches an
    interface that has gone quiet, which failure counts alone never would.

Silent-gap detection is delegated to the pure ``detect_silent_gap`` so the decision is
deterministic and unit-testable; the clock is passed in.
"""
from __future__ import annotations

import time
from typing import Any

from clinara_integration_sdk.ratelimit import detect_silent_gap
from django.utils import timezone

from clinara.middleware.tenant import current_tenant_id, set_db_tenant

from .models import (
    Alert,
    AlertSeverity,
    DeadLetterEvent,
    DeadLetterStatus,
    InboundMessage,
    InboundStatus,
    Integration,
    IntegrationError,
    IntegrationStatus,
)


def _bind(tenant_id: str) -> None:
    current_tenant_id.set(str(tenant_id))
    set_db_tenant(str(tenant_id))


def integration_health(tenant_id: str, integration_id: str) -> dict[str, Any]:
    """Per-interface health snapshot (spec §6.7.5)."""
    _bind(tenant_id)
    integration = Integration.objects.get(id=integration_id, tenant_id=tenant_id)
    errors = IntegrationError.objects.filter(tenant_id=tenant_id, integration=integration)
    inbound = InboundMessage.objects.filter(tenant_id=tenant_id, integration=integration)
    dead = DeadLetterEvent.objects.filter(tenant_id=tenant_id, integration=integration)
    return {
        "id": str(integration.id),
        "name": integration.name,
        "kind": integration.kind,
        "status": integration.status,
        "last_seen_at": integration.last_seen_at.isoformat() if integration.last_seen_at else None,
        "last_sequence": integration.last_sequence,
        "throughput": inbound.count(),
        "processed": inbound.filter(status=InboundStatus.PROCESSED).count(),
        "malformed": errors.filter(kind="malformed").count(),
        "rate_limited": errors.filter(kind="rate_limited").count(),
        "dead_letter_open": dead.filter(status=DeadLetterStatus.OPEN).count(),
        "open_alerts": Alert.objects.filter(
            tenant_id=tenant_id, integration=integration, resolved=False
        ).count(),
    }


def scan_silent_gaps(tenant_id: str, now_epoch: float | None = None) -> list[Alert]:
    """Raise a critical alert for any interface silent past its grace window (spec §12.3).

    Idempotent per interface: an interface already carrying an open ``silent_gap`` alert is
    not re-alerted, and its status is flipped to DISCONNECTED so the health board reflects it.
    """
    now_epoch = time.time() if now_epoch is None else now_epoch
    _bind(tenant_id)
    raised: list[Alert] = []
    for integration in Integration.objects.filter(tenant_id=tenant_id).exclude(
        expected_interval_seconds=0
    ):
        last_seen = integration.last_seen_at.timestamp() if integration.last_seen_at else None
        if not detect_silent_gap(
            last_seen_epoch=last_seen, now_epoch=now_epoch,
            expected_interval_seconds=integration.expected_interval_seconds,
        ):
            continue
        already = Alert.objects.filter(
            tenant_id=tenant_id, integration=integration, kind="silent_gap", resolved=False
        ).exists()
        if already:
            continue
        alert = Alert.objects.create(
            tenant_id=tenant_id, integration=integration, kind="silent_gap",
            severity=AlertSeverity.CRITICAL,
            message=f"No traffic from {integration.name} within expected window",
        )
        integration.status = IntegrationStatus.DISCONNECTED
        integration.save(update_fields=["status", "updated_at"])
        raised.append(alert)
    return raised


def dashboard(tenant_id: str) -> dict[str, Any]:
    """Tenant-wide integration health board (spec §12.3)."""
    _bind(tenant_id)
    interfaces = [
        integration_health(tenant_id, str(i.id))
        for i in Integration.objects.filter(tenant_id=tenant_id)
    ]
    return {
        "interfaces": interfaces,
        "open_alerts": Alert.objects.filter(tenant_id=tenant_id, resolved=False).count(),
        "dead_letter_open": DeadLetterEvent.objects.filter(
            tenant_id=tenant_id, status=DeadLetterStatus.OPEN
        ).count(),
        "generated_at": timezone.now().isoformat(),
    }


__all__ = ["integration_health", "scan_silent_gaps", "dashboard"]
