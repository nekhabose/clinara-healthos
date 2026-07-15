"""Refills service interface (spec §7.4, plan Phase 4 — the second governed workflow).

Wires the pure deterministic engine (``refills.core.evaluate_refill``) to persistence,
audit, and the outbox. Medication identity is resolved deterministically (RxNorm); an
unresolved identity blocks automation. Auto-approve fires only for an explicitly
client-approved low-risk class with all safety preconditions clean; everything else becomes
a reviewable workflow for a nurse/prescriber. No medication change is ever LLM-generated.
"""
from __future__ import annotations

import uuid
from typing import Any

from clinara_shared_types import EventType, RefillOutcome
from clinara_terminology import (
    ControlledSchedule,
    MedicationClass,
    MedicationSpec,
    UnknownMedicationError,
    map_medication,
)
from django.db import transaction

from clinara.middleware.phi_safe_logging import correlation_id as _correlation_id
from clinara.middleware.tenant import current_tenant_id, set_db_tenant
from core.outbox import publish_event
from domains.audit import services as audit
from domains.operations import services as operations

from .core import RefillContext, evaluate_refill
from .models import (
    AllergyIntolerance,
    ClientMonitoringPolicy,
    MedicationStatement,
    RefillEvaluationRecord,
    RefillReview,
    RefillReviewAction,
    RefillStatus,
    RefillWorkflow,
)

# Which engine outcomes map to which reviewable workflow status.
_STATUS_BY_OUTCOME = {
    RefillOutcome.AUTO_APPROVE: RefillStatus.AUTO_APPROVED,
    RefillOutcome.ONE_CLICK_PREPARED: RefillStatus.PENDING_REVIEW,
    RefillOutcome.ROUTE_TO_NURSE: RefillStatus.ROUTED,
    RefillOutcome.ROUTE_TO_PRESCRIBER: RefillStatus.ROUTED,
    RefillOutcome.REQUEST_LABS: RefillStatus.PENDING_REVIEW,
    RefillOutcome.REQUEST_APPOINTMENT: RefillStatus.PENDING_REVIEW,
    RefillOutcome.REJECT_TOO_EARLY: RefillStatus.REJECTED,
    RefillOutcome.REJECT_DISCONTINUED: RefillStatus.REJECTED,
    RefillOutcome.ESCALATE_CONTRAINDICATION: RefillStatus.ESCALATED,
    RefillOutcome.ESCALATE_MISSING_DATA: RefillStatus.ESCALATED,
    RefillOutcome.ESCALATE_CONTROLLED_SUBSTANCE: RefillStatus.ESCALATED,
}


def _bind(tenant_id: str, correlation: str) -> None:
    current_tenant_id.set(str(tenant_id))
    _correlation_id.set(correlation)
    set_db_tenant(str(tenant_id))


def _resolve_medication(code_system: str, code: str) -> MedicationSpec | None:
    try:
        return map_medication(code_system, code)
    except UnknownMedicationError:
        return None


def _build_context(tenant_id: str, patient: str, med: MedicationSpec | None,
                   payload: dict[str, Any]) -> RefillContext:
    """Assemble the deterministic factor set (spec §6.3.2) from stored patient data + payload."""
    allergies = tuple(
        AllergyIntolerance.objects.filter(tenant_id=tenant_id, patient_external_id=patient)
        .values_list("substance", flat=True)
    )
    statement = None
    if med is not None:
        statement = (
            MedicationStatement.objects.filter(
                tenant_id=tenant_id, patient_external_id=patient, rxnorm=med.rxnorm
            ).order_by("-created_at").first()
        )
    policy = None
    if med is not None:
        policy = ClientMonitoringPolicy.objects.filter(
            tenant_id=tenant_id, med_class=med.med_class.value
        ).first()

    auto_classes: frozenset[MedicationClass] = frozenset()
    if policy is not None and policy.auto_approve:
        auto_classes = frozenset({MedicationClass(policy.med_class)})

    return RefillContext(
        medication=med,
        requested_dose=payload.get("requested_dose"),
        prescribed_dose=(statement.prescribed_dose if statement else None)
        or payload.get("prescribed_dose"),
        active=(statement.active if statement else payload.get("active", True)),
        discontinued=(statement.discontinued if statement else payload.get("discontinued", False)),
        days_since_last_fill=(statement.last_fill_days_ago if statement
                              else payload.get("days_since_last_fill")),
        days_supply=(statement.days_supply if statement else payload.get("days_supply")),
        last_visit_days_ago=payload.get("last_visit_days_ago"),
        visit_required_within_days=(policy.visit_required_within_days if policy else None),
        monitoring_labs_overdue=bool(payload.get("monitoring_labs_overdue", False))
        and (policy.requires_monitoring_labs if policy else True),
        allergies=allergies,
        contraindications=tuple(payload.get("contraindications", [])),
        interactions=tuple(payload.get("interactions", [])),
        pregnancy=bool(payload.get("pregnancy", False)),
        renal_impairment=bool(payload.get("renal_impairment", False)),
        hepatic_impairment=bool(payload.get("hepatic_impairment", False)),
        client_auto_approve_classes=auto_classes,
    )


def process_refill_request(*, tenant_id: str, payload: dict[str, Any]) -> RefillWorkflow:
    """Evaluate one refill request end to end (spec §6.3). Deterministic; LLM-free."""
    correlation = payload.get("idempotency_key") or str(uuid.uuid4())
    _bind(tenant_id, correlation)
    patient = str(payload["patient_external_id"])
    code_system = payload.get("code_system", "RXNORM")
    code = str(payload["code"])

    med = _resolve_medication(code_system, code)
    ctx = _build_context(tenant_id, patient, med, payload)
    decision = evaluate_refill(ctx)

    with transaction.atomic():
        workflow = RefillWorkflow.objects.create(
            tenant_id=tenant_id, correlation_id=correlation, patient_external_id=patient,
            rxnorm=code, medication_name=(med.name if med else ""),
            requested_dose=payload.get("requested_dose", "") or "",
            outcome=decision.outcome.value,
            controlled_substance=decision.controlled_substance,
            automation_allowed=decision.automation_allowed,
            status=_STATUS_BY_OUTCOME[decision.outcome],
        )
        RefillEvaluationRecord.objects.create(
            tenant_id=tenant_id, workflow=workflow, outcome=decision.outcome.value,
            reason_codes=decision.reason_codes, required_actions=decision.required_actions,
            clinical_factors_used=decision.clinical_factors_used,
            decision={
                "outcome": decision.outcome.value,
                "reason_codes": decision.reason_codes,
                "required_actions": decision.required_actions,
                "clinical_factors_used": decision.clinical_factors_used,
                "controlled_substance": decision.controlled_substance,
                "automation_allowed": decision.automation_allowed,
            },
        )

        # Unresolved medication identity is also parked on the ops queue (never dropped).
        if med is None:
            operations.enqueue(
                tenant_id=tenant_id, kind=operations.QueueKind.UNMAPPED_CODE,
                reference=correlation, detail=f"RXNORM:{code}",
            )

        audit.record(
            actor="system", action="refill_decision", resource=f"refill:{workflow.id}",
            reason=decision.outcome.value,
            after_state={"outcome": decision.outcome.value,
                         "controlled": decision.controlled_substance,
                         "automation_allowed": decision.automation_allowed},
        )
        publish_event(
            event_type=EventType.REFILL_EVALUATED.value,
            idempotency_key=f"{correlation}:evaluated",
            payload={"workflow_id": str(workflow.id), "outcome": decision.outcome.value,
                     "controlled": decision.controlled_substance},
        )
    return workflow


# ---- Human actions (spec §6.3.6). Controlled/escalated flows always require a human. ----

def _act(workflow_id: str, tenant_id: str, actor: str, action: str,
         new_status: str, reason: str = "") -> RefillWorkflow:
    _bind(tenant_id, str(uuid.uuid4()))
    with transaction.atomic():
        workflow = RefillWorkflow.objects.get(id=workflow_id, tenant_id=tenant_id)
        before = workflow.status
        RefillReview.objects.create(
            tenant_id=tenant_id, workflow=workflow, action=action, actor=actor, reason=reason
        )
        workflow.status = new_status
        workflow.save(update_fields=["status", "updated_at"])
        audit.record(actor=actor, action="refill_action", resource=f"refill:{workflow.id}",
                     reason=reason or action,
                     before_state={"status": before}, after_state={"status": new_status})
        publish_event(
            event_type=EventType.REFILL_DECIDED.value,
            idempotency_key=f"{workflow.id}:{action}:{uuid.uuid4()}",
            payload={"workflow_id": str(workflow.id), "action": action, "actor": actor},
        )
    return workflow


def approve(workflow_id: str, *, tenant_id: str, actor: str) -> RefillWorkflow:
    return _act(workflow_id, tenant_id, actor, RefillReviewAction.APPROVE, RefillStatus.APPROVED)


def reject(workflow_id: str, *, tenant_id: str, actor: str, reason: str = "") -> RefillWorkflow:
    return _act(workflow_id, tenant_id, actor, RefillReviewAction.REJECT, RefillStatus.REJECTED,
                reason)


def route(workflow_id: str, *, tenant_id: str, actor: str, reason: str = "") -> RefillWorkflow:
    return _act(workflow_id, tenant_id, actor, RefillReviewAction.ROUTE, RefillStatus.ROUTED,
                reason)


def escalate(workflow_id: str, *, tenant_id: str, actor: str, reason: str) -> RefillWorkflow:
    return _act(workflow_id, tenant_id, actor, RefillReviewAction.ESCALATE,
                RefillStatus.ESCALATED, reason)


# Small helper so tests / seeds can register patient medication + allergy facts.
def upsert_medication_statement(*, tenant_id: str, patient_external_id: str, rxnorm: str,
                                **fields) -> MedicationStatement:
    _bind(tenant_id, str(uuid.uuid4()))
    spec = None
    try:
        spec = map_medication("RXNORM", rxnorm)
    except UnknownMedicationError:
        pass
    defaults = {
        "name": spec.name if spec else fields.get("name", ""),
        "med_class": spec.med_class.value if spec else fields.get("med_class", ""),
        "schedule": (spec.schedule.value if spec else ControlledSchedule.NONE.value),
        **{k: v for k, v in fields.items() if k not in {"name", "med_class", "schedule"}},
    }
    statement, _ = MedicationStatement.objects.update_or_create(
        tenant_id=tenant_id, patient_external_id=patient_external_id, rxnorm=rxnorm,
        defaults=defaults,
    )
    return statement


__all__ = [
    "process_refill_request", "approve", "reject", "route", "escalate",
    "upsert_medication_statement",
]
