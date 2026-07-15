"""Workflows service interface (spec §7.4) — the Phase 1 orchestrator.

Wires the pure pipeline (``workflows.core.run_result_pipeline``) to persistence, audit, and
the transactional outbox. This is the ONLY place clinical results are turned into
reviewable workflow instances. Every mutating clinician action is audited and emits a
domain event; nothing that fails is dropped — it is parked on the operations queue.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from functools import lru_cache
from typing import Any

from clinara_clinical_models import ContextProvenance, ContextSnapshot
from clinara_protocol_engine import Rule, evaluate, load_rules
from clinara_shared_types import AutomationStatus, EventType, ResultClassification
from clinara_terminology import CanonicalMarker
from django.conf import settings
from django.db import transaction
from django.utils import timezone

from clinara.middleware.phi_safe_logging import correlation_id as _correlation_id
from clinara.middleware.tenant import current_tenant_id, set_db_tenant
from core.outbox import publish_event
from domains.audit import services as audit
from domains.clinical_data.models import Observation, PatientReference
from domains.context.core import snapshot_hash
from domains.context.models import ContextSnapshotRecord
from domains.generation.services import get_templates
from domains.operations import services as operations
from domains.terminology import services as terminology

from .core import run_result_pipeline
from .models import (
    Escalation,
    GeneratedCommunication,
    HumanReview,
    ProtocolEvaluationRecord,
    ReviewAction,
    WorkflowInstance,
    WorkflowStatus,
)


@lru_cache(maxsize=1)
def _rules() -> tuple[Rule, ...]:
    return tuple(load_rules(settings.CLINICAL_RULES_DIR))


def _bind_context(tenant_id: str, correlation: str) -> None:
    """Pin tenant + correlation for RLS and event/audit stamping (works off-request too)."""
    current_tenant_id.set(str(tenant_id))
    _correlation_id.set(correlation)
    set_db_tenant(str(tenant_id))


def _status_for(decision) -> str:
    if decision.classification is ResultClassification.UNSUPPORTED:
        return WorkflowStatus.BLOCKED
    if decision.automation_status is AutomationStatus.SUPPRESSED_MISSING_CONTEXT:
        return WorkflowStatus.SUPPRESSED
    return WorkflowStatus.PENDING_REVIEW


def process_inbound(message) -> WorkflowInstance | None:
    """Process one stored InboundMessage end to end. Idempotent per message."""
    from domains.integrations.models import InboundStatus  # local import avoids app-load cycle

    tenant_id = str(message.tenant_id)
    correlation = message.idempotency_key
    _bind_context(tenant_id, correlation)

    p: dict[str, Any] = message.raw_payload
    system, code = p["code_system"], p["code"]
    value, unit = float(p["value"]), p.get("unit")
    observed_at = _parse_dt(p["observed_at"])
    patient_ext = str(p["patient_external_id"])
    patient_facts = p.get("patient_facts") or {}
    specialty = p.get("specialty")
    ref = p.get("reference_range") or {}
    now = timezone.now()

    marker = terminology.resolve_marker(tenant_id, system, code)

    with transaction.atomic():
        # Unknown code → visible queue, never dropped (spec §6.1.6).
        if marker is None:
            terminology.record_unknown_code(
                tenant_id=tenant_id, code_system=system, code=code,
                sample_payload={"code_system": system, "code": code},
            )
            operations.enqueue(
                tenant_id=tenant_id, kind=operations.QueueKind.UNMAPPED_CODE,
                reference=message.idempotency_key, detail=f"{system}:{code}",
            )
            message.status = InboundStatus.PROCESSED
            message.save(update_fields=["status", "updated_at"])
            return None

        patient, _ = PatientReference.objects.get_or_create(
            tenant_id=tenant_id, external_id=patient_ext
        )
        prior = (
            Observation.objects.filter(
                tenant_id=tenant_id, patient=patient, marker=marker.value,
                observed_at__lt=observed_at,
            )
            .order_by("-observed_at")
            .values_list("value", flat=True)
            .first()
        )

        result = run_result_pipeline(
            tenant_id=tenant_id, patient_id=patient_ext, system=system, code=code,
            value=value, unit=unit, observed_at=observed_at, now=now,
            rules=list(_rules()), templates=get_templates(),
            patient_facts=patient_facts, prior_value=prior,
            ref_low=ref.get("low"), ref_high=ref.get("high"),
            specialty=specialty, source_record_ids=[message.idempotency_key],
            resolved_marker=marker,
        )
        decision = result.evaluation.decision

        observation_id = None
        if result.observation.is_usable:
            obs = Observation.objects.create(
                tenant_id=tenant_id, patient=patient, code_system=system, code=code,
                marker=marker.value, value=result.observation.value,
                unit=result.observation.canonical_unit,
                original_value=result.observation.original_value,
                original_unit=result.observation.original_unit or "",
                observed_at=observed_at, inbound_message_id=message.id,
            )
            observation_id = obs.id

        workflow = WorkflowInstance.objects.create(
            tenant_id=tenant_id, correlation_id=correlation, patient_external_id=patient_ext,
            observation_id=observation_id, marker=marker.value,
            classification=decision.classification.value, priority=decision.priority.value,
            automation_status=decision.automation_status.value, status=_status_for(decision),
        )

        snap = result.snapshot
        ContextSnapshotRecord.objects.create(
            tenant_id=tenant_id, workflow_id=workflow.id, patient_external_id=patient_ext,
            snapshot_hash=snapshot_hash(snap), facts=snap.facts,
            provenance=snap.provenance.model_dump(mode="json"),
            builder_version=snap.provenance.context_builder_version,
        )
        ProtocolEvaluationRecord.objects.create(
            tenant_id=tenant_id, workflow=workflow, marker=marker.value,
            matched_rule_id=result.evaluation.trace.matched_rule_id or "",
            matched_rule_version=result.evaluation.trace.matched_rule_version,
            critical_triggered=result.evaluation.trace.critical_triggered,
            decision=decision.model_dump(mode="json"),
            trace=result.evaluation.trace.model_dump(mode="json"),
        )
        val = result.validation
        GeneratedCommunication.objects.create(
            tenant_id=tenant_id, workflow=workflow,
            template_key=decision.patient_message_template or "",
            patient_message=val.final_patient_message or "",
            clinician_summary=val.final_clinician_summary,
            validation_passed=val.passed, validation_failures=val.failures,
            used_fallback=val.used_fallback,
        )

        if decision.classification is ResultClassification.UNSUPPORTED:
            operations.enqueue(
                tenant_id=tenant_id, kind=operations.QueueKind.UNSUPPORTED_UNIT,
                reference=message.idempotency_key, detail=f"{marker.value}:{unit}",
            )

        audit.record(
            actor="system", action="workflow_decision", resource=f"workflow:{workflow.id}",
            reason=decision.classification.value,
            after_state={
                "classification": decision.classification.value,
                "priority": decision.priority.value,
                "automation_status": decision.automation_status.value,
                "validation_passed": val.passed,
            },
        )

        base = message.idempotency_key
        _emit(EventType.PROTOCOL_EVALUATED, f"{base}:evaluated", workflow, marker.value)
        _emit(EventType.DECISION_CREATED, f"{base}:decided", workflow, marker.value)
        _emit(EventType.COMMUNICATION_VALIDATED, f"{base}:validated", workflow, marker.value,
              extra={"validation_passed": val.passed})

        message.status = InboundStatus.PROCESSED
        message.save(update_fields=["status", "updated_at"])

    return workflow


def _emit(event_type: EventType, key: str, workflow, marker: str, extra=None) -> None:
    payload = {"workflow_id": str(workflow.id), "marker": marker,
               "classification": workflow.classification, "priority": workflow.priority}
    if extra:
        payload.update(extra)
    publish_event(event_type=event_type.value, idempotency_key=key, payload=payload)


# ---- Human review actions (spec §6.10.1). Every action is audited + emits an event. ----

def _act(workflow_id: str, tenant_id: str, actor: str, action: str,
         new_status: str, event: EventType, *, edited_message: str = "", reason: str = ""):
    _bind_context(tenant_id, str(uuid.uuid4()))
    with transaction.atomic():
        workflow = WorkflowInstance.objects.get(id=workflow_id, tenant_id=tenant_id)
        before = workflow.status
        HumanReview.objects.create(
            tenant_id=tenant_id, workflow=workflow, action=action, actor=actor,
            edited_message=edited_message, reason=reason,
        )
        workflow.status = new_status
        workflow.save(update_fields=["status", "updated_at"])
        audit.record(
            actor=actor, action="clinician_action", resource=f"workflow:{workflow.id}",
            reason=reason or action,
            before_state={"status": before}, after_state={"status": new_status},
        )
        publish_event(
            event_type=event.value,
            idempotency_key=f"{workflow.id}:{action}:{uuid.uuid4()}",
            payload={"workflow_id": str(workflow.id), "actor": actor, "action": action},
        )
    return workflow


def approve(workflow_id: str, *, tenant_id: str, actor: str):
    return _act(workflow_id, tenant_id, actor, ReviewAction.APPROVE,
                WorkflowStatus.APPROVED, EventType.CLINICIAN_APPROVED)


def edit(workflow_id: str, *, tenant_id: str, actor: str, edited_message: str):
    return _act(workflow_id, tenant_id, actor, ReviewAction.EDIT,
                WorkflowStatus.EDITED, EventType.CLINICIAN_EDITED, edited_message=edited_message)


def override(workflow_id: str, *, tenant_id: str, actor: str, reason: str):
    return _act(workflow_id, tenant_id, actor, ReviewAction.OVERRIDE,
                WorkflowStatus.OVERRIDDEN, EventType.CLINICIAN_OVERRODE, reason=reason)


def reject(workflow_id: str, *, tenant_id: str, actor: str, reason: str = ""):
    return _act(workflow_id, tenant_id, actor, ReviewAction.REJECT,
                WorkflowStatus.CLOSED, EventType.CLINICIAN_OVERRODE, reason=reason)


def escalate(workflow_id: str, *, tenant_id: str, actor: str, reason: str):
    _bind_context(tenant_id, str(uuid.uuid4()))
    with transaction.atomic():
        workflow = WorkflowInstance.objects.get(id=workflow_id, tenant_id=tenant_id)
        Escalation.objects.create(tenant_id=tenant_id, workflow=workflow, reason=reason)
        HumanReview.objects.create(
            tenant_id=tenant_id, workflow=workflow, action=ReviewAction.ESCALATE,
            actor=actor, reason=reason,
        )
        workflow.status = WorkflowStatus.ESCALATED
        workflow.save(update_fields=["status", "updated_at"])
        audit.record(actor=actor, action="clinician_action", resource=f"workflow:{workflow.id}",
                     reason=f"escalate:{reason}")
        publish_event(
            event_type=EventType.WORKFLOW_ESCALATED.value,
            idempotency_key=f"{workflow.id}:escalate:{uuid.uuid4()}",
            payload={"workflow_id": str(workflow.id), "reason": reason},
        )
    return workflow


def replay(workflow_id: str, *, tenant_id: str) -> dict[str, Any]:
    """Re-evaluate the stored snapshot and confirm the decision reproduces (plan §1.1)."""
    _bind_context(tenant_id, str(uuid.uuid4()))
    record = ContextSnapshotRecord.objects.filter(
        tenant_id=tenant_id, workflow_id=workflow_id
    ).latest("created_at")
    stored = ProtocolEvaluationRecord.objects.filter(
        tenant_id=tenant_id, workflow_id=workflow_id
    ).latest("created_at")

    snapshot = ContextSnapshot(
        tenant_id=tenant_id, patient_id=record.patient_external_id, facts=record.facts,
        provenance=ContextProvenance(**record.provenance),
        context_created_at=_parse_dt(record.provenance["source_timestamps"]["observation"])
        if record.provenance.get("source_timestamps") else timezone.now(),
    )
    marker = CanonicalMarker(record.facts["lab.marker"]) if record.facts.get("lab.marker") \
        else CanonicalMarker(stored.marker)
    specialty = record.facts.get("context.specialty")
    replayed = evaluate(snapshot, marker=marker, rules=list(_rules()), specialty=specialty)
    return {
        "matches": replayed.decision.model_dump(mode="json") == stored.decision,
        "stored": stored.decision,
        "replayed": replayed.decision.model_dump(mode="json"),
    }


def _parse_dt(value: str | datetime) -> datetime:
    if isinstance(value, datetime):
        dt = value
    else:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.get_current_timezone())
    return dt


__all__ = [
    "process_inbound", "approve", "edit", "override", "reject", "escalate", "replay",
]
