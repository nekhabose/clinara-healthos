"""Public service interface for Billing & Coding Intelligence (spec §7.4; plan Phase 9 — G1).

The ONLY entry point other modules use to interact with this domain. It runs the deterministic
detectors (``core``), persists suggestions as an inert review queue, and enforces the
governance invariants that make a coding module safe to ship:

  * **Nothing auto-applies.** Suggestions are created ``PENDING``. Only ``confirm_suggestion``
    (a human action, actor-attributed) advances one, and only a ``CONFIRMED`` suggestion can be
    ``export``-ed to coding/claim. There is no code path that applies a suggestion without a
    human in the loop.
  * **Every decision is audited and evidence-linked.** Each write records an ``AuditEvent`` with
    the actor and the deterministic evidence, and publishes a domain event.
  * **The loop is governed.** Confirmations/rejections feed the Phase 6 analytics loop as
    ``coding`` feedback (approve/override), so acceptance and override rates are tracked exactly
    like every other clinician action — no separate, ungoverned metric.
"""
from __future__ import annotations

import uuid

from clinara_shared_types import EventType
from django.db import transaction
from django.utils import timezone

from clinara.middleware.phi_safe_logging import correlation_id as _correlation_id
from clinara.middleware.tenant import current_tenant_id, set_db_tenant
from core.outbox import publish_event
from domains.audit import services as audit
from domains.context.models import ContextSnapshotRecord
from domains.feedback import services as feedback

from . import core
from .models import CodingSuggestionRecord, SuggestionStatus


class SuggestionNotFound(LookupError):
    """No coding suggestion exists for the requested id in this tenant."""


class SuggestionStateError(RuntimeError):
    """The suggestion is not in a state that permits the requested transition."""


def _bind(tenant_id: str) -> None:
    current_tenant_id.set(str(tenant_id))
    if not _correlation_id.get():
        _correlation_id.set(str(uuid.uuid4()))
    set_db_tenant(str(tenant_id))


# --------------------------------------------------------------------------------------
# Analysis → review queue
# --------------------------------------------------------------------------------------

def analyze_encounter(
    *,
    tenant_id: str,
    patient_external_id: str,
    problem_list: list[core.ProblemListItem] | None = None,
    encounter_dx: list[core.EncounterDiagnosis] | None = None,
    facts: dict | None = None,
    lab_values: dict[str, float] | None = None,
    workflow_id: str | None = None,
    encounter_id: str = "",
    snapshot_hash: str = "",
) -> list[CodingSuggestionRecord]:
    """Run the deterministic detectors and upsert the resulting suggestions as PENDING.

    Idempotent: re-analysing the same chart refreshes the evidence/rationale of an existing
    *pending* suggestion for the same gap rather than creating a duplicate, and never resurrects
    a suggestion a human already confirmed or rejected.
    """
    _bind(tenant_id)
    analysis = core.analyze(
        facts=facts, lab_values=lab_values,
        problem_list=problem_list, encounter_dx=encounter_dx,
    )
    records: list[CodingSuggestionRecord] = []
    with transaction.atomic():
        for s in analysis.suggestions:
            existing = CodingSuggestionRecord.objects.filter(
                tenant_id=tenant_id, patient_external_id=patient_external_id,
                encounter_id=encounter_id, dedup_key=s.dedup_key,
            ).first()
            if existing is not None:
                # A human decision is final — never re-open a decided suggestion.
                if existing.status == SuggestionStatus.PENDING:
                    existing.evidence = list(s.evidence)
                    existing.rationale = s.rationale
                    existing.snapshot_hash = snapshot_hash or existing.snapshot_hash
                    existing.save(update_fields=["evidence", "rationale", "snapshot_hash",
                                                 "updated_at"])
                records.append(existing)
                continue
            rec = CodingSuggestionRecord.objects.create(
                tenant_id=tenant_id, workflow_id=workflow_id,
                patient_external_id=patient_external_id, encounter_id=encounter_id,
                snapshot_hash=snapshot_hash, suggestion_type=s.suggestion_type.value,
                icd10_code=s.icd10_code, description=s.description, hcc=s.hcc or "",
                supersedes_code=s.supersedes_code or "",
                requires_provider_confirmation=s.requires_provider_confirmation,
                rationale=s.rationale, evidence=list(s.evidence), dedup_key=s.dedup_key,
                status=SuggestionStatus.PENDING,
            )
            records.append(rec)
        audit.record(
            actor="system", action="coding_suggestions_generated",
            resource=f"encounter:{encounter_id or patient_external_id}",
            reason=f"{len(records)} suggestion(s)",
            after_state={"count": len(records),
                         "types": sorted({r.suggestion_type for r in records})},
        )
        publish_event(
            event_type=EventType.CODING_SUGGESTIONS_GENERATED.value,
            idempotency_key=f"coding-generated:{tenant_id}:{patient_external_id}:"
                            f"{encounter_id}:{analysis_digest(analysis)}",
            payload={"patient_external_id": patient_external_id, "encounter_id": encounter_id,
                     "count": len(records)},
        )
    return records


def analyze_from_snapshot(
    *,
    tenant_id: str,
    workflow_id: str,
    problem_list: list[core.ProblemListItem] | None = None,
    encounter_dx: list[core.EncounterDiagnosis] | None = None,
    encounter_id: str = "",
) -> list[CodingSuggestionRecord]:
    """Analyse using the immutable ``ContextSnapshot`` a results workflow already produced.

    Reads exactly the chart context the protocol engine reasoned over (same snapshot as the
    Phase 8 context panel), so the coding suggestion rides on the same governed context — no
    new chart access, no re-fetch. Raises ``SuggestionNotFound`` if the workflow has no snapshot.
    """
    _bind(tenant_id)
    record = (
        ContextSnapshotRecord.objects.filter(tenant_id=tenant_id, workflow_id=workflow_id)
        .order_by("-created_at").first()
    )
    if record is None:
        raise SuggestionNotFound(f"no context snapshot for workflow {workflow_id}")
    return analyze_encounter(
        tenant_id=tenant_id, patient_external_id=record.patient_external_id,
        problem_list=problem_list, encounter_dx=encounter_dx, facts=record.facts,
        workflow_id=workflow_id, encounter_id=encounter_id, snapshot_hash=record.snapshot_hash,
    )


def analysis_digest(analysis: core.CodingAnalysis) -> str:
    """A stable content key for the set of suggestions (for event idempotency)."""
    return "|".join(sorted(s.dedup_key for s in analysis.suggestions)) or "none"


# --------------------------------------------------------------------------------------
# Human decisions (the only way anything advances)
# --------------------------------------------------------------------------------------

def _load(tenant_id: str, suggestion_id: str) -> CodingSuggestionRecord:
    rec = CodingSuggestionRecord.objects.filter(tenant_id=tenant_id, id=suggestion_id).first()
    if rec is None:
        raise SuggestionNotFound(f"no coding suggestion {suggestion_id}")
    return rec


def confirm_suggestion(
    *, tenant_id: str, suggestion_id: str, actor: str, reason: str = "",
    now=None,
) -> CodingSuggestionRecord:
    """A clinician confirms a suggestion. PENDING → CONFIRMED, audited with actor + evidence.

    This is the human-in-the-loop gate: only after this can the suggestion be exported. Feeds
    the Phase 6 analytics loop as a ``coding`` approval so acceptance rate is tracked.
    """
    _bind(tenant_id)
    now = now or timezone.now()
    with transaction.atomic():
        rec = _load(tenant_id, suggestion_id)
        if rec.status != SuggestionStatus.PENDING:
            raise SuggestionStateError(f"cannot confirm a {rec.status} suggestion")
        rec.status = SuggestionStatus.CONFIRMED
        rec.decided_by = actor
        rec.decided_at = now
        rec.decision_reason = reason
        rec.save(update_fields=["status", "decided_by", "decided_at", "decision_reason",
                                "updated_at"])
        audit.record(
            actor=actor, action="coding_suggestion_confirmed",
            resource=f"coding_suggestion:{rec.id}", reason=reason or rec.suggestion_type,
            after_state={"icd10_code": rec.icd10_code, "hcc": rec.hcc,
                         "evidence": rec.evidence, "status": rec.status},
        )
        publish_event(
            event_type=EventType.CODING_SUGGESTION_CONFIRMED.value,
            idempotency_key=f"coding-confirmed:{rec.id}",
            payload={"suggestion_id": str(rec.id), "icd10_code": rec.icd10_code,
                     "actor": actor},
        )
    _feed_analytics(tenant_id, rec, action="approve", actor=actor, reason=reason)
    return rec


def reject_suggestion(
    *, tenant_id: str, suggestion_id: str, actor: str, reason: str = "", now=None,
) -> CodingSuggestionRecord:
    """A clinician rejects a suggestion. PENDING → REJECTED, audited; feeds override rate."""
    _bind(tenant_id)
    now = now or timezone.now()
    with transaction.atomic():
        rec = _load(tenant_id, suggestion_id)
        if rec.status != SuggestionStatus.PENDING:
            raise SuggestionStateError(f"cannot reject a {rec.status} suggestion")
        rec.status = SuggestionStatus.REJECTED
        rec.decided_by = actor
        rec.decided_at = now
        rec.decision_reason = reason
        rec.save(update_fields=["status", "decided_by", "decided_at", "decision_reason",
                                "updated_at"])
        audit.record(
            actor=actor, action="coding_suggestion_rejected",
            resource=f"coding_suggestion:{rec.id}", reason=reason or rec.suggestion_type,
            after_state={"icd10_code": rec.icd10_code, "status": rec.status},
        )
        publish_event(
            event_type=EventType.CODING_SUGGESTION_REJECTED.value,
            idempotency_key=f"coding-rejected:{rec.id}",
            payload={"suggestion_id": str(rec.id), "icd10_code": rec.icd10_code,
                     "actor": actor},
        )
    _feed_analytics(tenant_id, rec, action="override", actor=actor, reason=reason)
    return rec


def export_suggestion(
    *, tenant_id: str, suggestion_id: str, actor: str, now=None,
) -> CodingSuggestionRecord:
    """Release a CONFIRMED suggestion to coding/claim. The export gate: a suggestion that was
    not human-confirmed can NEVER be exported (raises ``SuggestionStateError``)."""
    _bind(tenant_id)
    now = now or timezone.now()
    with transaction.atomic():
        rec = _load(tenant_id, suggestion_id)
        if rec.status != SuggestionStatus.CONFIRMED:
            raise SuggestionStateError(
                "only a clinician-confirmed suggestion can be exported "
                f"(status is {rec.status})"
            )
        rec.status = SuggestionStatus.EXPORTED
        rec.save(update_fields=["status", "updated_at"])
        audit.record(
            actor=actor, action="coding_suggestion_exported",
            resource=f"coding_suggestion:{rec.id}", reason="release to coding",
            before_state={"status": SuggestionStatus.CONFIRMED},
            after_state={"icd10_code": rec.icd10_code, "status": rec.status},
        )
        publish_event(
            event_type=EventType.CODING_SUGGESTION_EXPORTED.value,
            idempotency_key=f"coding-exported:{rec.id}",
            payload={"suggestion_id": str(rec.id), "icd10_code": rec.icd10_code},
        )
    return rec


def list_suggestions(
    *, tenant_id: str, status: str | None = None, workflow_id: str | None = None,
) -> list[CodingSuggestionRecord]:
    _bind(tenant_id)
    qs = CodingSuggestionRecord.objects.filter(tenant_id=tenant_id)
    if status:
        qs = qs.filter(status=status)
    if workflow_id:
        qs = qs.filter(workflow_id=workflow_id)
    return list(qs[:500])


def _feed_analytics(tenant_id: str, rec: CodingSuggestionRecord, *, action: str,
                    actor: str, reason: str) -> None:
    """Route a coding decision into the governed Phase 6 loop as ``coding`` feedback."""
    feedback.capture(
        tenant_id=tenant_id, workflow_type="coding", workflow_id=str(rec.id),
        practitioner=actor, action=action, protocol_key=rec.icd10_code, reason=reason,
    )


__all__ = [
    "analyze_encounter", "analyze_from_snapshot", "confirm_suggestion", "reject_suggestion",
    "export_suggestion", "list_suggestions", "SuggestionNotFound", "SuggestionStateError",
]
