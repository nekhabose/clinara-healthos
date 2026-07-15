"""Pure results pipeline orchestrator (plan Phase 1 — the §1.1 pipeline, end to end).

Composes the governed pipeline as a single deterministic function so the whole flow is
unit-testable without a database, a broker, or an LLM:

    canonicalize → build snapshot → evaluate protocol → (generate → validate)

The Django ``services.py`` calls this and then persists the result, writes audit records,
and publishes domain events. Keeping the logic here means the API layer is thin and the
safety-critical path is covered by fast, deterministic tests.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from clinara_clinical_models import ContextSnapshot, ProtocolEvaluation
from clinara_protocol_engine import Rule, evaluate

from domains.clinical_data.core import CanonicalObservation, canonicalize
from domains.context.core import build_snapshot
from domains.generation.core import CommunicationTemplate, Draft, LLMClient, draft
from domains.safety.core import ValidationResult, validate


@dataclass(frozen=True)
class PipelineResult:
    status: str  # "decided" | "unmapped_code"
    observation: CanonicalObservation
    snapshot: ContextSnapshot | None = None
    evaluation: ProtocolEvaluation | None = None
    draft: Draft | None = None
    validation: ValidationResult | None = None
    queue_signal: str | None = None  # ops-queue reason, e.g. "unmapped_code"


def run_result_pipeline(
    *,
    tenant_id: str,
    patient_id: str,
    system: str,
    code: str,
    value: float,
    unit: str | None,
    observed_at: datetime,
    now: datetime,
    rules: list[Rule],
    templates: dict[str, CommunicationTemplate],
    patient_facts: dict | None = None,
    prior_value: float | None = None,
    ref_low: float | None = None,
    ref_high: float | None = None,
    specialty: str | None = None,
    source_record_ids: list[str] | None = None,
    conflicting_facts: list[str] | None = None,
    resolved_marker=None,
    llm: LLMClient | None = None,
) -> PipelineResult:
    """Run one lab result end to end and return every intermediate artifact."""
    observation = canonicalize(
        system=system, code=code, value=value, unit=unit, observed_at=observed_at,
        resolved_marker=resolved_marker,
    )

    # Unknown code: never dropped — park it on the unmapped-code queue (spec §6.1.6).
    if observation.unknown_code:
        return PipelineResult(
            status="unmapped_code", observation=observation, queue_signal="unmapped_code"
        )

    snapshot = build_snapshot(
        tenant_id=tenant_id,
        patient_id=patient_id,
        observation=observation,
        now=now,
        patient_facts=patient_facts,
        prior_value=prior_value,
        ref_low=ref_low,
        ref_high=ref_high,
        specialty=specialty,
        source_record_ids=source_record_ids,
        conflicting_facts=conflicting_facts,
    )

    # ``marker`` is present even for unsupported units (unit blocked, code known).
    assert observation.marker is not None
    evaluation = evaluate(
        snapshot, marker=observation.marker, rules=rules, specialty=specialty
    )

    the_draft = draft(evaluation.decision, snapshot, templates, llm=llm)
    validation = validate(the_draft, evaluation.decision, snapshot)

    return PipelineResult(
        status="decided",
        observation=observation,
        snapshot=snapshot,
        evaluation=evaluation,
        draft=the_draft,
        validation=validation,
    )
