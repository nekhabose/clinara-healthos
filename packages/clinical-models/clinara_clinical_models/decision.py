"""Structured result decision (spec §6.1.5) and its evaluation trace.

This is the deterministic output of the protocol engine. It exists *before* any LLM is
called (plan §1.1 invariant 1): classification, priority, recommended action, reason
codes, and the exact clinical facts used are all decided by governed rules. The LLM later
drafts communication *from* this object — it can never change it.

``ResultDecision`` mirrors the spec §6.1.5 JSON shape exactly so it round-trips to the
API and audit log unchanged. ``EvaluationTrace`` carries the replay/explainability detail
(which rule matched, at which version, what was considered) referenced by plan §1.1.
"""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from clinara_shared_types import (
    AutomationStatus,
    Priority,
    ResultClassification,
)


class ResultDecision(BaseModel):
    """The governed, deterministic decision for one result (spec §6.1.5).

    Frozen: once produced, the decision is immutable. Communication generation and the
    validation gate read it but never mutate it — the deterministic outcome is preserved
    even if generation fails (spec §6.9.6).
    """

    model_config = ConfigDict(frozen=True)

    classification: ResultClassification
    priority: Priority
    recommended_action: str
    recommended_interval_days: int | None = None
    automation_status: AutomationStatus
    patient_message_template: str | None = None
    reason_codes: list[str] = Field(default_factory=list)
    clinical_facts_used: list[str] = Field(default_factory=list)

    @property
    def is_critical(self) -> bool:
        return self.classification == ResultClassification.CRITICAL_ESCALATION

    @property
    def requires_human(self) -> bool:
        """True whenever this decision must not be auto-delivered.

        In Phase 1 every decision requires a human, but this property also encodes the
        permanent safety invariants (critical / missing-context / unsupported) so later
        phases that introduce automation cannot accidentally bypass them.
        """
        return self.automation_status != AutomationStatus.REQUIRES_CLINICIAN_APPROVAL or (
            self.classification
            in {
                ResultClassification.CRITICAL_ESCALATION,
                ResultClassification.HIGH_PRIORITY_REVIEW,
                ResultClassification.CONFLICTING_DATA,
                ResultClassification.INSUFFICIENT_DATA,
                ResultClassification.UNSUPPORTED,
            }
        )


class EvaluationTrace(BaseModel):
    """Replayable record of *how* a decision was reached (plan §1.1 explainability)."""

    model_config = ConfigDict(frozen=True)

    marker: str
    matched_rule_id: str | None = None
    matched_rule_version: int | None = None
    critical_triggered: bool = False
    rules_considered: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class ProtocolEvaluation(BaseModel):
    """A decision plus its trace — the engine's full return value."""

    model_config = ConfigDict(frozen=True)

    decision: ResultDecision
    trace: EvaluationTrace
