"""Analytics & governed personalization — pure core (plan Phase 6; spec §12, §6.4.3).

Closes the loop: accumulated clinician feedback becomes governed analytics and
*approval-gated* personalization that can **never weaken safety**. Two hard rules from the
plan shape everything here:

  * **Personalization is a recommendation engine, not an actuator** — derived preferences and
    config recommendations are inert data until a human approves them and they flow through
    the Phase 2 deployment pipeline. Nothing here mutates live behaviour.
  * **De-identification is mandatory for any cross-tenant learning** — identifiers are
    stripped and small cells are suppressed before anything leaves a tenant boundary.

Django-free and deterministic so the aggregation, preference-derivation, safety guard, and
privacy controls are exhaustively unit-testable.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

# --------------------------------------------------------------------------------------
# Edit-difference analysis (spec §12 — what clinicians change and why)
# --------------------------------------------------------------------------------------

@dataclass(frozen=True)
class EditDifference:
    original_length: int
    edited_length: int
    added_words: list[str]
    removed_words: list[str]

    @property
    def length_delta(self) -> int:
        return self.edited_length - self.original_length

    @property
    def shortened(self) -> bool:
        return self.length_delta < 0

    def as_dict(self) -> dict:
        return {
            "original_length": self.original_length,
            "edited_length": self.edited_length,
            "length_delta": self.length_delta,
            "shortened": self.shortened,
            "added_words": self.added_words,
            "removed_words": self.removed_words,
        }


def edit_difference(original: str, edited: str) -> EditDifference:
    """Structured diff between a generated draft and a clinician's edit."""
    o_words = original.split()
    e_words = edited.split()
    o_set, e_set = set(o_words), set(e_words)
    return EditDifference(
        original_length=len(o_words),
        edited_length=len(e_words),
        added_words=sorted(e_set - o_set),
        removed_words=sorted(o_set - e_set),
    )


# --------------------------------------------------------------------------------------
# Feedback aggregation (spec §12 — agreement / edit / override / escalation analytics)
# --------------------------------------------------------------------------------------

@dataclass(frozen=True)
class FeedbackMetrics:
    total: int
    approvals: int
    edits: int
    overrides: int
    escalations: int

    @property
    def agreement_rate(self) -> float:
        return round(self.approvals / self.total, 4) if self.total else 0.0

    @property
    def edit_rate(self) -> float:
        return round(self.edits / self.total, 4) if self.total else 0.0

    @property
    def override_rate(self) -> float:
        return round(self.overrides / self.total, 4) if self.total else 0.0

    @property
    def escalation_rate(self) -> float:
        return round(self.escalations / self.total, 4) if self.total else 0.0

    def as_dict(self) -> dict:
        return {
            "total": self.total, "approvals": self.approvals, "edits": self.edits,
            "overrides": self.overrides, "escalations": self.escalations,
            "agreement_rate": self.agreement_rate, "edit_rate": self.edit_rate,
            "override_rate": self.override_rate, "escalation_rate": self.escalation_rate,
        }


def aggregate_feedback(actions: list[str]) -> FeedbackMetrics:
    """Aggregate a list of clinician actions into governed rate metrics."""
    c = Counter(actions)
    return FeedbackMetrics(
        total=len(actions),
        approvals=c.get("approve", 0),
        edits=c.get("edit", 0),
        overrides=c.get("override", 0),
        escalations=c.get("escalate", 0),
    )


# --------------------------------------------------------------------------------------
# Preference derivation (spec §6.4.3) — signals only, never safety-weakening
# --------------------------------------------------------------------------------------

# Fields a preference may adjust: purely low-risk wording / tone / cadence. Anything that
# could touch a safety-critical decision is NOT in this set and is rejected by the guard.
PREFERENCE_ALLOWED_FIELDS: frozenset[str] = frozenset(
    {"tone", "verbosity", "follow_up_interval_days", "greeting", "signature"}
)

# Fields that are safety-critical and can NEVER be personalized (spec §6.4.3, §11.1).
SAFETY_PROTECTED_FIELDS: frozenset[str] = frozenset(
    {"critical_threshold", "classification", "required_warning", "automation_status",
     "priority", "red_flag", "controlled_substance_policy"}
)


class PreferenceSafetyViolation(ValueError):
    """Raised when a preference would touch a safety-protected field."""


def assert_preference_safe(adjustments: dict) -> None:
    """Reject any preference adjustment that touches a safety-protected field (spec §6.4.3).

    A preference is provably incapable of weakening safety: it may only set fields in the
    low-risk allowlist, and any protected field is a hard error.
    """
    for field_name in adjustments:
        if field_name in SAFETY_PROTECTED_FIELDS or field_name not in PREFERENCE_ALLOWED_FIELDS:
            raise PreferenceSafetyViolation(
                f"preference field {field_name!r} is not a personalizable low-risk field"
            )


@dataclass(frozen=True)
class PreferenceSignal:
    practitioner: str
    adjustments: dict
    derived_from: int  # number of feedback observations behind this signal

    def validated(self) -> PreferenceSignal:
        assert_preference_safe(self.adjustments)
        return self


def derive_preferences(practitioner: str, edits: list[EditDifference],
                       *, min_observations: int = 3) -> PreferenceSignal | None:
    """Derive a low-risk preference signal from a clinician's edit pattern.

    Only fires with enough observations (avoids over-fitting to one edit) and only ever
    proposes allowlisted low-risk adjustments — the returned signal is validated so it can
    never weaken safety.
    """
    if len(edits) < min_observations:
        return None
    shortened = sum(1 for e in edits if e.shortened)
    adjustments: dict = {}
    if shortened >= (len(edits) + 1) // 2:
        adjustments["verbosity"] = "concise"
    if not adjustments:
        return None
    return PreferenceSignal(
        practitioner=practitioner, adjustments=adjustments, derived_from=len(edits)
    ).validated()


# --------------------------------------------------------------------------------------
# Governed configuration recommendations (plan Phase 6 — approval-gated, never autonomous)
# --------------------------------------------------------------------------------------

@dataclass(frozen=True)
class ConfigRecommendation:
    kind: str            # e.g. "template_wording", "follow_up_interval"
    target: str          # what it would change (template key, protocol key, …)
    proposal: dict       # the proposed change (data only — inert until approved)
    rationale: str
    supporting_observations: int

    def as_dict(self) -> dict:
        return {
            "kind": self.kind, "target": self.target, "proposal": self.proposal,
            "rationale": self.rationale, "supporting_observations": self.supporting_observations,
        }


def recommend_from_signal(signal: PreferenceSignal, *, target: str) -> ConfigRecommendation:
    """Turn a validated preference signal into an *inert* config recommendation.

    The recommendation is pure data; it takes effect only after human approval routes it
    through the Phase 2 governed deployment pipeline (plan Phase 6 key decision).
    """
    assert_preference_safe(signal.adjustments)  # defence in depth
    return ConfigRecommendation(
        kind="preference_personalization",
        target=target,
        proposal={"adjustments": signal.adjustments, "practitioner": signal.practitioner},
        rationale=f"Derived from {signal.derived_from} clinician edits.",
        supporting_observations=signal.derived_from,
    )


# --------------------------------------------------------------------------------------
# Privacy controls (spec §12.5) — aggregation thresholds + de-identification
# --------------------------------------------------------------------------------------

# HIPAA-style small-cell suppression threshold: cells below this are not reported.
DEFAULT_MIN_CELL = 11


def suppress_small_cells(cells: dict[str, int], *, min_cell: int = DEFAULT_MIN_CELL
                         ) -> dict[str, int | str]:
    """Suppress any cohort cell smaller than ``min_cell`` (spec §12.5 aggregation threshold)."""
    return {k: (v if v >= min_cell else "suppressed") for k, v in cells.items()}


_IDENTIFIER_KEYS = frozenset(
    {"patient_external_id", "patient_id", "actor", "clinician", "practitioner",
     "name", "mrn", "email"}
)


def deidentify(record: dict) -> dict:
    """Strip direct identifiers for any cross-tenant analysis (spec §4.2, §12.5).

    De-identification is mandatory before data leaves a tenant boundary — no model training
    on identifiable customer data without explicit authorization.
    """
    return {k: v for k, v in record.items() if k not in _IDENTIFIER_KEYS}


@dataclass(frozen=True)
class Dashboards:
    executive: dict = field(default_factory=dict)
    clinical: dict = field(default_factory=dict)
    operations: dict = field(default_factory=dict)


__all__ = [
    "EditDifference", "edit_difference",
    "FeedbackMetrics", "aggregate_feedback",
    "PreferenceSignal", "derive_preferences", "assert_preference_safe",
    "PreferenceSafetyViolation", "PREFERENCE_ALLOWED_FIELDS", "SAFETY_PROTECTED_FIELDS",
    "ConfigRecommendation", "recommend_from_signal",
    "suppress_small_cells", "deidentify", "DEFAULT_MIN_CELL",
    "Dashboards",
]
