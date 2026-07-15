"""Output validation & safety gate (plan Phase 1, workstream 7 — spec §6.9.5/§6.9.6).

Every generated message must pass a battery of deterministic checks before it can reach a
clinician's review queue. If ANY check fails, generation is discarded and replaced with an
approved fixed-template fallback routed to a human — the deterministic clinical decision is
always preserved (spec §6.9.6). Django-free and deterministic.

Checks implemented (subset of spec §6.9.5 relevant to Phase 1 results):
  schema, numeric consistency, fact consistency, required-warning, prohibited-claim,
  PHI boundary, template compliance, hallucination (via numeric/claim checks).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from clinara_clinical_models import ContextSnapshot, ResultDecision

from domains.generation.core import Draft, build_context

# Numbers NOT touching a letter (so "A1c" -> no match, "7.4%" -> 7.4, "1.73m2" -> no match).
_NUMBER = re.compile(r"(?<![A-Za-z0-9])\d+(?:\.\d+)?(?![A-Za-z0-9])")
_SSN = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
_EMAIL = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")

# Phrases a patient message must never contain — they assert an unconfirmed diagnosis or
# treatment (spec §6.1.6, §6.9.4). Deliberately conservative.
_PROHIBITED = (
    "you have been diagnosed",
    "you have diabetes",
    "this confirms",
    "you have cancer",
    "start taking",
    "stop taking",
    "you should take",
    "increase your dose",
    "decrease your dose",
)

# Fixed, approved fallback (spec §6.9.6). Generic, safe, non-diagnostic; always to a human.
FALLBACK_PATIENT_MESSAGE = (
    "Your recent test result is ready and will be reviewed by your care team. "
    "They will contact you if any follow-up is needed. "
    "This is general information, not a diagnosis."
)


@dataclass
class ValidationResult:
    passed: bool
    failures: list[str] = field(default_factory=list)
    final_patient_message: str | None = None
    final_clinician_summary: str = ""
    used_fallback: bool = False
    route_to_human: bool = True  # Phase 1: always true


def _numbers(text: str) -> set[str]:
    return {m.group().rstrip("0").rstrip(".") if "." in m.group() else m.group()
            for m in _NUMBER.finditer(text)}


def _allowed_numbers(decision: ResultDecision, snapshot: ContextSnapshot) -> set[str]:
    ctx = build_context(decision, snapshot)
    allowed: set[str] = set()
    for key in ("value", "prior", "interval"):
        allowed |= _numbers(ctx.get(key, ""))
    facts = snapshot.facts
    for fk in ("lab.ref_low", "lab.ref_high"):
        v = facts.get(fk)
        if v is not None:
            allowed |= _numbers(str(v))
    return allowed


def validate(draft: Draft, decision: ResultDecision, snapshot: ContextSnapshot) -> ValidationResult:
    """Run the gate. On failure, substitute the approved fallback and route to a human."""
    failures: list[str] = []

    # schema: a clinician always needs a non-empty summary.
    if not draft.clinician_summary.strip():
        failures.append("schema:empty_clinician_summary")

    patient = draft.patient_message
    if patient is not None:
        # template compliance
        tmpl_key = draft.template.key if draft.template is not None else None
        if draft.template is None or draft.template_key != tmpl_key:
            failures.append("template_compliance:missing_or_mismatched_template")

        # numeric consistency / hallucination: no number may appear that isn't a known fact.
        allowed = _allowed_numbers(decision, snapshot)
        stray = _numbers(patient) - allowed
        if stray:
            failures.append(f"numeric_consistency:unexpected_numbers:{sorted(stray)}")

        # required-warning
        if draft.template is not None:
            for warning in draft.template.required_warnings:
                if warning not in patient:
                    failures.append(f"required_warning:missing:{warning!r}")

        # prohibited-claim
        low = patient.lower()
        for phrase in _PROHIBITED:
            if phrase in low:
                failures.append(f"prohibited_claim:{phrase!r}")

        # PHI boundary
        if _SSN.search(patient) or _EMAIL.search(patient):
            failures.append("phi_boundary:identifier_in_message")

    if failures:
        return ValidationResult(
            passed=False,
            failures=failures,
            final_patient_message=(FALLBACK_PATIENT_MESSAGE if patient is not None else None),
            final_clinician_summary=(
                draft.clinician_summary.strip() or "Result requires clinician review."
            ),
            used_fallback=True,
            route_to_human=True,
        )

    return ValidationResult(
        passed=True,
        failures=[],
        final_patient_message=patient,
        final_clinician_summary=draft.clinician_summary,
        used_fallback=False,
        route_to_human=True,
    )
