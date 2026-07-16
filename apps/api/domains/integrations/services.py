"""Integrations service interface (spec §7.4) — Phase 1 sandbox ingestion.

Stores the raw payload first, derives a stable idempotency key, and dedupes duplicate
deliveries before handing off to the workflow orchestrator. A duplicate is a no-op: it
never double-processes or double-communicates (spec §6.7.6).
"""
from __future__ import annotations

import hashlib
import json
from typing import Any

from django.db import transaction

from clinara.middleware.phi_safe_logging import correlation_id as _correlation_id
from clinara.middleware.tenant import current_tenant_id, set_db_tenant
from core.outbox import publish_event

from .models import InboundMessage, InboundStatus, Integration


def register_integration(
    *, tenant_id: str, name: str, kind: str, source_system: str = "",
    expected_interval_seconds: int = 0, rate_capacity: int = 100,
    rate_refill_per_second: float = 50.0,
) -> Integration:
    """Register a production interface (spec §6.7). Idempotent per (tenant, name)."""
    current_tenant_id.set(str(tenant_id))
    set_db_tenant(str(tenant_id))
    integration, _ = Integration.objects.get_or_create(
        tenant_id=tenant_id, name=name,
        defaults={
            "kind": kind, "source_system": source_system,
            "expected_interval_seconds": expected_interval_seconds,
            "rate_capacity": rate_capacity, "rate_refill_per_second": rate_refill_per_second,
        },
    )
    return integration


def derive_idempotency_key(tenant_id: str, payload: dict[str, Any]) -> str:
    """Stable key from the identifying fields of a result (spec §6.7.6)."""
    material = json.dumps(
        {
            "tenant": str(tenant_id),
            "patient": payload.get("patient_external_id"),
            "system": payload.get("code_system"),
            "code": payload.get("code"),
            "observed_at": payload.get("observed_at"),
            "value": payload.get("value"),
        },
        sort_keys=True,
    )
    return "obs:" + hashlib.sha256(material.encode()).hexdigest()[:40]


def ingest_result(
    *, tenant_id: str, payload: dict[str, Any], source: str = "fhir-sandbox",
    integration_id: str | None = None,
) -> tuple[InboundMessage, bool]:
    """Persist the raw result idempotently. Returns (message, created)."""
    current_tenant_id.set(str(tenant_id))
    set_db_tenant(str(tenant_id))
    key = derive_idempotency_key(tenant_id, payload)

    with transaction.atomic():
        message, created = InboundMessage.objects.get_or_create(
            idempotency_key=key,
            defaults={
                "tenant_id": tenant_id, "source": source, "integration_id": integration_id,
                "message_type": payload.get("resource_type", "Observation"),
                "raw_payload": payload, "status": InboundStatus.RECEIVED,
            },
        )
        if created:
            _correlation_id.set(key)
            publish_event(
                event_type="ObservationReceived", idempotency_key=f"{key}:received",
                payload={"message_type": message.message_type, "source": source},
            )
    return message, created


def ingest_and_process(*, tenant_id: str, payload: dict[str, Any], source: str = "fhir-sandbox",
                       integration_id: str | None = None):
    """Ingest then process. Returns (message, workflow_or_None, created)."""
    from domains.workflows import services as workflows

    message, created = ingest_result(
        tenant_id=tenant_id, payload=payload, source=source, integration_id=integration_id
    )
    if not created and message.status == InboundStatus.PROCESSED:
        return message, None, False  # duplicate; already handled — never reprocess
    workflow = workflows.process_inbound(message)
    return message, workflow, created


__all__ = [
    "ingest_result", "ingest_and_process", "derive_idempotency_key", "register_integration",
]
