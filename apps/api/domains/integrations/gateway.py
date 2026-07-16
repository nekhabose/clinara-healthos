"""Hardened Integration Gateway (plan Phase 3, workstream 1 — spec §6.7.4).

The production front door for real HL7/FHIR traffic. It authenticates the shape of an
inbound message, resolves the tenant + interface, stores the raw payload, rate-limits abusive
sources, guards against malformed payloads, dedupes duplicates, normalizes timestamps, and
publishes canonical events — with **zero silent loss**: anything it cannot process is
dead-lettered (visible, replayable), never dropped (plan §1.1 invariant 2).

Vendor parsing is delegated to the adapters (`clinara_integration_sdk`); the gateway itself
is format-agnostic and only ever emits canonical payloads downstream.
"""
from __future__ import annotations

import time
import uuid
from typing import Any

from clinara_integration_sdk import Hl7ParseError, to_canonical_payloads
from clinara_integration_sdk import parse as parse_hl7
from clinara_integration_sdk.ratelimit import TokenBucket
from clinara_shared_types import EventType
from django.db import transaction
from django.utils import timezone

from clinara.middleware.phi_safe_logging import correlation_id as _correlation_id
from clinara.middleware.tenant import current_tenant_id, set_db_tenant
from core.outbox import publish_event

from . import services as ingestion
from .fhir import FhirParseError, parse_observation
from .models import (
    DeadLetterEvent,
    Integration,
    IntegrationError,
    RateLimitState,
)


class RateLimited(RuntimeError):
    pass


def _bind(tenant_id: str, correlation: str | None = None) -> None:
    current_tenant_id.set(str(tenant_id))
    _correlation_id.set(correlation or str(uuid.uuid4()))
    set_db_tenant(str(tenant_id))


def _check_rate(integration: Integration, source_key: str, now_epoch: float) -> bool:
    """Persisted token-bucket check per (integration, source). Returns True if allowed."""
    state, _ = RateLimitState.objects.get_or_create(
        tenant_id=integration.tenant_id, integration=integration, source_key=source_key,
        defaults={"tokens": float(integration.rate_capacity), "last_refill": now_epoch},
    )
    bucket = TokenBucket(
        capacity=float(integration.rate_capacity),
        refill_per_second=integration.rate_refill_per_second,
        tokens=state.tokens, last_refill=state.last_refill,
    )
    allowed = bucket.allow(now_epoch)
    state.tokens = bucket.tokens
    state.last_refill = bucket.last_refill
    state.save(update_fields=["tokens", "last_refill", "updated_at"])
    return allowed


def _dead_letter(integration: Integration, *, raw: dict, error: str,
                 idempotency_key: str = "") -> DeadLetterEvent:
    return DeadLetterEvent.objects.create(
        tenant_id=integration.tenant_id, integration=integration, raw=raw,
        error=error[:255], idempotency_key=idempotency_key,
    )


def _touch_heartbeat(integration: Integration, sequence: int | None) -> None:
    integration.last_seen_at = timezone.now()
    if sequence is not None:
        integration.last_sequence = sequence
    integration.save(update_fields=["last_seen_at", "last_sequence", "updated_at"])


def receive_fhir(*, integration_id: str, resource: dict[str, Any],
                 now_epoch: float | None = None, source_key: str = "default"):
    """Receive one FHIR resource through the hardened gateway. Returns a result dict.

    Malformed → dead-letter. Rate-limited → rejected + error recorded. Otherwise the
    resource is lowered to a canonical payload and processed idempotently (duplicates are a
    no-op).
    """
    now_epoch = time.time() if now_epoch is None else now_epoch
    integration = Integration.objects.get(id=integration_id)
    tenant_id = str(integration.tenant_id)
    _bind(tenant_id)

    if not _check_rate(integration, source_key, now_epoch):
        IntegrationError.objects.create(
            tenant_id=tenant_id, integration=integration, kind="rate_limited",
            detail=source_key,
        )
        return {"status": "rate_limited"}

    try:
        payload = parse_observation(resource) if resource.get("resourceType") == "Observation" \
            else _reject_unsupported(resource)
    except FhirParseError as exc:
        IntegrationError.objects.create(
            tenant_id=tenant_id, integration=integration, kind="malformed", detail=str(exc)[:255]
        )
        dl = _dead_letter(integration, raw=resource, error=f"fhir:{exc}")
        return {"status": "dead_lettered", "dead_letter_id": str(dl.id)}

    _touch_heartbeat(integration, integration.last_sequence + 1)
    _, workflow, created = ingestion.ingest_and_process(
        tenant_id=tenant_id, payload=payload, source=integration.name,
        integration_id=str(integration.id),
    )
    return {"status": "processed" if workflow else "queued_or_duplicate",
            "created": created,
            "workflow_id": str(workflow.id) if workflow else None}


def _reject_unsupported(resource: dict[str, Any]) -> dict[str, Any]:
    rtype = resource.get("resourceType", "unknown")
    raise FhirParseError(f"unsupported resourceType {rtype!r} for result ingestion")


def receive_hl7(*, integration_id: str, raw_message: str,
                now_epoch: float | None = None, source_key: str = "default"):
    """Receive one HL7 v2 message. ORU results are lowered to canonical + processed.

    ADT/ORM/MDM carry no numeric result — a PatientUpdated/EncounterUpdated event is emitted
    (nothing dropped). Malformed HL7 → dead-letter.
    """
    now_epoch = time.time() if now_epoch is None else now_epoch
    integration = Integration.objects.get(id=integration_id)
    tenant_id = str(integration.tenant_id)
    _bind(tenant_id)

    if not _check_rate(integration, source_key, now_epoch):
        IntegrationError.objects.create(
            tenant_id=tenant_id, integration=integration, kind="rate_limited", detail=source_key
        )
        return {"status": "rate_limited"}

    try:
        message = parse_hl7(raw_message)
    except Hl7ParseError as exc:
        IntegrationError.objects.create(
            tenant_id=tenant_id, integration=integration, kind="malformed", detail=str(exc)[:255]
        )
        dl = _dead_letter(integration, raw={"hl7": raw_message[:4000]}, error=f"hl7:{exc}")
        return {"status": "dead_lettered", "dead_letter_id": str(dl.id)}

    _touch_heartbeat(integration, integration.last_sequence + 1)

    if message.category in {"ADT", "ORM", "MDM"}:
        with transaction.atomic():
            event = (EventType.ENCOUNTER_UPDATED if message.category == "ADT"
                     else EventType.PATIENT_UPDATED)
            publish_event(
                event_type=event.value,
                idempotency_key=f"{integration.id}:{message.message_control_id}",
                payload={"category": message.category,
                         "patient_external_id": message.patient_external_id,
                         "encounter_id": message.encounter_id},
            )
        return {"status": "acknowledged", "category": message.category}

    results = []
    for payload in to_canonical_payloads(message):
        _, workflow, created = ingestion.ingest_and_process(
            tenant_id=tenant_id, payload=payload, source=integration.name,
            integration_id=str(integration.id),
        )
        results.append({"created": created,
                        "workflow_id": str(workflow.id) if workflow else None})
    return {"status": "processed", "category": message.category, "results": results}


def replay_dead_letter(*, tenant_id: str, dead_letter_id: str,
                       now_epoch: float | None = None):
    """Reprocess a dead-lettered event idempotently (plan Phase 3 exit gate).

    Because ingestion is keyed by idempotency, replaying a message that has since become
    processable never produces a duplicate task/communication.
    """
    _bind(tenant_id)
    dl = DeadLetterEvent.objects.get(id=dead_letter_id, tenant_id=tenant_id)
    integration = dl.integration
    dl.replay_count += 1
    if "hl7" in dl.raw and integration is not None:
        result = receive_hl7(integration_id=str(integration.id),
                             raw_message=dl.raw["hl7"], now_epoch=now_epoch)
    elif integration is not None:
        result = receive_fhir(integration_id=str(integration.id),
                              resource=dl.raw, now_epoch=now_epoch)
    else:
        result = {"status": "no_integration"}

    if result.get("status") not in {"dead_lettered", "rate_limited", "no_integration"}:
        dl.status = "replayed"
    dl.save(update_fields=["status", "replay_count", "updated_at"])
    return {"dead_letter_id": str(dl.id), "result": result, "status": dl.status}


__all__ = ["receive_fhir", "receive_hl7", "replay_dead_letter", "RateLimited"]
