"""Constrained communication generation (plan Phase 1, workstream 6 — spec §6.9.4).

The LLM is a PURE FUNCTION of (approved template + structured facts). It may simplify or
rewrite tone; it may never choose thresholds, diagnose, invent facts, or weaken warnings.
The default renderer uses NO LLM at all — it fills the approved template deterministically,
which guarantees the platform still produces safe output if the model is removed
(plan §1.1 invariant 1). An optional ``LLMClient`` can be injected to soften tone; whatever
it returns is still policed by the validation gate (safety/core.py).

Django-free and deterministic (with the default renderer).
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import yaml
from clinara_clinical_models import ContextSnapshot, ResultDecision
from clinara_terminology import MARKER_SPECS, CanonicalMarker


class LLMClient(Protocol):
    def rewrite(self, text: str, instruction: str) -> str: ...


@dataclass(frozen=True)
class CommunicationTemplate:
    key: str
    version: int
    patient_body: str
    clinician_body: str
    required_warnings: list[str]
    reading_level_max: int


@dataclass(frozen=True)
class Draft:
    patient_message: str | None
    clinician_summary: str
    template_key: str | None
    template: CommunicationTemplate | None


# Fixed, approved clinician-only summary used when there is no patient template (criticals,
# blocked/insufficient results). It never asserts a diagnosis.
_CLINICIAN_ONLY_BODY = (
    "{marker_display}: {value} {unit} (prior {prior}, trend {trend}).\n"
    "Classification: {classification}. Reason codes: {reason_codes}. Requires clinician handling."
)


class _SafeDict(dict):
    def __missing__(self, key: str) -> str:  # missing placeholder renders empty, never crashes
        return ""


def load_templates(path: str | Path) -> dict[str, CommunicationTemplate]:
    raw = yaml.safe_load(Path(path).read_text()) or {}
    templates: dict[str, CommunicationTemplate] = {}
    for key, data in raw.items():
        templates[key] = CommunicationTemplate(
            key=key,
            version=int(data.get("version", 1)),
            patient_body=data["patient_body"].strip(),
            clinician_body=data["clinician_body"].strip(),
            required_warnings=list(data.get("required_warnings", [])),
            reading_level_max=int(data.get("reading_level_max", 8)),
        )
    return templates


def _fmt_number(x: object) -> str:
    if x is None:
        return "not available"
    if isinstance(x, float):
        return f"{x:.1f}".rstrip("0").rstrip(".")
    return str(x)


def build_context(decision: ResultDecision, snapshot: ContextSnapshot) -> dict[str, str]:
    """Assemble the STRUCTURED-FACTS-ONLY substitution context. No chart free-text."""
    facts = snapshot.facts
    marker_value = facts.get("lab.marker")
    display = "result"
    if marker_value:
        display = MARKER_SPECS[CanonicalMarker(marker_value)].display_name
    return {
        "marker_display": display,
        "value": _fmt_number(facts.get("lab.value")),
        "unit": facts.get("lab.unit") or "",
        "prior": _fmt_number(facts.get("lab.prior_value")),
        "trend": facts.get("lab.trend") or "unknown",
        "action": decision.recommended_action,
        "interval": _fmt_number(decision.recommended_interval_days),
        "reason_codes": ", ".join(decision.reason_codes),
        "classification": decision.classification.value,
        "priority": decision.priority.value,
    }


def draft(
    decision: ResultDecision,
    snapshot: ContextSnapshot,
    templates: dict[str, CommunicationTemplate],
    *,
    llm: LLMClient | None = None,
) -> Draft:
    """Draft the patient message + clinician summary from approved inputs only."""
    ctx = build_context(decision, snapshot)
    key = decision.patient_message_template

    if not key or key not in templates:
        # No approved patient template → clinician-only path (safe by construction).
        clinician = _CLINICIAN_ONLY_BODY.format_map(_SafeDict(ctx))
        return Draft(
            patient_message=None, clinician_summary=clinician, template_key=None, template=None
        )

    template = templates[key]
    patient = template.patient_body.format_map(_SafeDict(ctx))
    clinician = template.clinician_body.format_map(_SafeDict(ctx))
    if llm is not None:
        # Tone-only rewrite. Any factual/numeric drift is rejected downstream by the gate.
        patient = llm.rewrite(
            patient,
            "Simplify tone and reading level. Do NOT change any facts, numbers, or warnings.",
        )
    return Draft(
        patient_message=patient, clinician_summary=clinician, template_key=key, template=template
    )
