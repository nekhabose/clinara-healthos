"""Deterministic coding-gap detectors (plan Phase 9 — closes G1).

Given the canonical chart context (the immutable ``ContextSnapshot`` facts), the documented
problem list, and the diagnoses already on the encounter, this module flags three kinds of
**revenue-integrity gap** as *suggestions* — never as applied codes:

  1. **Documented-but-uncoded** — an active problem carries an ICD-10 code that is absent
     from the encounter's diagnosis set.
  2. **HCC / risk-adjustment gap** — objective clinical evidence (a lab value at/over a
     diagnostic threshold) supports a risk-adjustable condition that is neither documented
     nor coded ("suspected-but-unaddressed"). Always flagged *suspected*, requiring provider
     confirmation — you can never code a suspected diagnosis without the provider.
  3. **Specificity upgrade** — the encounter carries an unspecified code but the chart
     supports a more specific one (e.g. unspecified CKD + an eGFR that stages it).

The governing invariant (``gaps.md §1``, ``plan.md §1``): every suggestion is **deterministic
and evidence-linked**. This module is pure and Django-free so the anti-upcoding guardrails are
exhaustively unit-testable. The two hard guardrails are enforced here:

  * **No evidence ⇒ no suggestion.** A suggestion is only produced when a concrete supporting
    fact is present; ``analyze`` drops (and asserts against) any evidence-less suggestion.
  * **Conservative thresholds.** Diabetes below the diagnostic A1c threshold, or CKD at
    eGFR >= 60, produce nothing — the module never reaches for the higher-weighted code.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from . import catalog


class SuggestionType(str, Enum):
    DOCUMENTED_UNCODED = "documented_uncoded"
    HCC_GAP = "hcc_gap"
    SPECIFICITY_UPGRADE = "specificity_upgrade"


@dataclass(frozen=True)
class ProblemListItem:
    """One entry from the patient's documented problem list."""
    description: str
    code: str | None = None
    status: str = "active"  # active | resolved | inactive


@dataclass(frozen=True)
class EncounterDiagnosis:
    """One diagnosis already attached to the encounter / claim."""
    code: str
    description: str = ""


@dataclass(frozen=True)
class CodingSuggestion:
    suggestion_type: SuggestionType
    icd10_code: str
    description: str
    rationale: str
    evidence: tuple[str, ...]
    hcc: str | None = None
    supersedes_code: str | None = None
    # Suspected diagnoses (HCC gaps) can never be coded without the provider affirming them.
    requires_provider_confirmation: bool = True

    @property
    def dedup_key(self) -> str:
        """Stable identity so re-analysis of the same chart is idempotent."""
        return f"{self.suggestion_type.value}:{self.icd10_code}:{self.supersedes_code or ''}"

    def as_dict(self) -> dict:
        return {
            "suggestion_type": self.suggestion_type.value,
            "icd10_code": self.icd10_code,
            "description": self.description,
            "rationale": self.rationale,
            "evidence": list(self.evidence),
            "hcc": self.hcc,
            "supersedes_code": self.supersedes_code,
            "requires_provider_confirmation": self.requires_provider_confirmation,
            "dedup_key": self.dedup_key,
        }


@dataclass(frozen=True)
class CodingAnalysis:
    suggestions: tuple[CodingSuggestion, ...] = field(default_factory=tuple)

    def as_dict(self) -> dict:
        return {"suggestions": [s.as_dict() for s in self.suggestions]}


# --------------------------------------------------------------------------------------
# Fact extraction from the canonical snapshot
# --------------------------------------------------------------------------------------

def lab_values_from_facts(facts: dict) -> dict[str, float]:
    """Pull the canonical lab value(s) out of a ``ContextSnapshot.facts`` dict.

    A results snapshot carries a single lab (``lab.marker`` / ``lab.value``). Callers with a
    fuller encounter view may pass an explicit ``lab_values`` map to ``analyze`` instead; this
    helper keeps the single-snapshot path faithful to the immutable snapshot shape.
    """
    marker = facts.get("lab.marker")
    value = facts.get("lab.value")
    if marker is None or value is None:
        return {}
    try:
        return {str(marker): float(value)}
    except (TypeError, ValueError):
        return {}


def _has_diabetes_documented(problem_list: list[ProblemListItem],
                             encounter_dx: list[EncounterDiagnosis]) -> bool:
    codes = _normalized_codes(problem_list, encounter_dx)
    texts = [p.description.lower() for p in problem_list]
    return (any(c.startswith("E11") or c.startswith("E10") for c in codes)
            or any("diabet" in t for t in texts))


def _has_ckd_documented(problem_list: list[ProblemListItem],
                        encounter_dx: list[EncounterDiagnosis]) -> bool:
    codes = _normalized_codes(problem_list, encounter_dx)
    texts = [p.description.lower() for p in problem_list]
    return (any(c.startswith("N18") for c in codes)
            or any("chronic kidney" in t or "ckd" in t for t in texts))


def _normalized_codes(problem_list: list[ProblemListItem],
                      encounter_dx: list[EncounterDiagnosis]) -> set[str]:
    codes = {catalog._normalize_code(d.code) for d in encounter_dx}
    codes |= {catalog._normalize_code(p.code) for p in problem_list if p.code}
    return codes


def _encounter_codes(encounter_dx: list[EncounterDiagnosis]) -> set[str]:
    return {catalog._normalize_code(d.code) for d in encounter_dx}


# --------------------------------------------------------------------------------------
# Detectors
# --------------------------------------------------------------------------------------

def detect_documented_uncoded(
    problem_list: list[ProblemListItem], encounter_dx: list[EncounterDiagnosis]
) -> list[CodingSuggestion]:
    """Active problems whose ICD-10 code is not on the encounter — documentation integrity."""
    encounter = _encounter_codes(encounter_dx)
    out: list[CodingSuggestion] = []
    for problem in problem_list:
        if problem.status != "active" or not problem.code:
            continue
        if catalog._normalize_code(problem.code) in encounter:
            continue
        hcc = catalog.hcc_for_code(problem.code)
        out.append(CodingSuggestion(
            suggestion_type=SuggestionType.DOCUMENTED_UNCODED,
            icd10_code=problem.code,
            description=problem.description,
            rationale=("Active problem-list condition is not represented in the encounter "
                       "diagnoses; documenting it improves coding completeness."),
            evidence=(f"Problem list (active): {problem.description} [{problem.code}]",
                      "Not present in encounter diagnosis set"),
            hcc=hcc,
        ))
    return out


def detect_hcc_gaps(
    lab_values: dict[str, float],
    problem_list: list[ProblemListItem],
    encounter_dx: list[EncounterDiagnosis],
) -> list[CodingSuggestion]:
    """Suspected-but-unaddressed risk-adjustable conditions from objective lab evidence.

    Only fires when the condition is neither documented nor coded, and only above a
    diagnostic threshold. Every result is flagged ``requires_provider_confirmation`` — a
    suspected diagnosis is a prompt to the provider, never an assertion.
    """
    out: list[CodingSuggestion] = []

    a1c = lab_values.get(catalog.MARKER_A1C)
    if (a1c is not None and a1c >= catalog.A1C_DIABETES_THRESHOLD
            and not _has_diabetes_documented(problem_list, encounter_dx)):
        code = catalog.DIABETES_UNSPECIFIED
        out.append(CodingSuggestion(
            suggestion_type=SuggestionType.HCC_GAP,
            icd10_code=code.code,
            description=code.description,
            rationale=(f"A1c {a1c}% is at/above the diagnostic threshold "
                       f"({catalog.A1C_DIABETES_THRESHOLD}%) with no diabetes on the problem "
                       "list or encounter — suspected, unaddressed. "
                       "Provider confirmation required."),
            evidence=(f"Hemoglobin A1c = {a1c}% (>= {catalog.A1C_DIABETES_THRESHOLD}% diagnostic)",
                      "No diabetes diagnosis documented or coded"),
            hcc=code.hcc,
        ))

    egfr = lab_values.get(catalog.MARKER_EGFR)
    if egfr is not None and not _has_ckd_documented(problem_list, encounter_dx):
        stage = catalog.ckd_stage_for_egfr(egfr)
        if stage is not None and stage.hcc is not None:
            out.append(CodingSuggestion(
                suggestion_type=SuggestionType.HCC_GAP,
                icd10_code=stage.code,
                description=stage.description,
                rationale=(f"eGFR {egfr} mL/min/1.73m2 indicates {stage.description.lower()} "
                           "with no CKD on the problem list or encounter — suspected, "
                           "unaddressed. Provider confirmation required."),
                evidence=(f"eGFR = {egfr} mL/min/1.73m2 "
                          f"(< {catalog.CKD_STAGE_FLOOR} = CKD stage 3+)",
                          "No chronic kidney disease diagnosis documented or coded"),
                hcc=stage.hcc,
            ))
    return out


def detect_specificity_upgrades(
    lab_values: dict[str, float], encounter_dx: list[EncounterDiagnosis]
) -> list[CodingSuggestion]:
    """Unspecified codes on the encounter that the chart can make more specific."""
    out: list[CodingSuggestion] = []
    encounter = _encounter_codes(encounter_dx)
    egfr = lab_values.get(catalog.MARKER_EGFR)

    # Unspecified CKD (N18.9) + a staging eGFR → specific stage.
    if egfr is not None:
        stage = catalog.ckd_stage_for_egfr(egfr)
        if stage is not None and catalog._normalize_code(catalog.CKD_UNSPECIFIED_CODE) in encounter:
            out.append(CodingSuggestion(
                suggestion_type=SuggestionType.SPECIFICITY_UPGRADE,
                icd10_code=stage.code,
                description=stage.description,
                rationale=(f"Encounter carries unspecified CKD ({catalog.CKD_UNSPECIFIED_CODE}); "
                           f"eGFR {egfr} stages it as {stage.description.lower()}."),
                evidence=(f"Encounter diagnosis {catalog.CKD_UNSPECIFIED_CODE} (unspecified)",
                          f"eGFR = {egfr} mL/min/1.73m2 supports {stage.code}"),
                hcc=stage.hcc,
                supersedes_code=catalog.CKD_UNSPECIFIED_CODE,
            ))

    # Diabetes without complications (E11.9) + CKD evidence → diabetes WITH diabetic CKD.
    if (egfr is not None and egfr < catalog.CKD_STAGE_FLOOR
            and catalog._normalize_code(catalog.DIABETES_UNSPECIFIED.code) in encounter):
        target = catalog.DIABETES_WITH_CKD
        out.append(CodingSuggestion(
            suggestion_type=SuggestionType.SPECIFICITY_UPGRADE,
            icd10_code=target.code,
            description=target.description,
            rationale=(f"Encounter carries {catalog.DIABETES_UNSPECIFIED.code} (diabetes without "
                       f"complications); eGFR {egfr} evidences diabetic CKD, a complication."),
            evidence=(f"Encounter diagnosis {catalog.DIABETES_UNSPECIFIED.code} "
                      "(without complications)",
                      f"eGFR = {egfr} mL/min/1.73m2 evidences chronic kidney disease"),
            hcc=target.hcc,
            supersedes_code=catalog.DIABETES_UNSPECIFIED.code,
        ))
    return out


# --------------------------------------------------------------------------------------
# Top-level analysis
# --------------------------------------------------------------------------------------

def analyze(
    *,
    facts: dict | None = None,
    lab_values: dict[str, float] | None = None,
    problem_list: list[ProblemListItem] | None = None,
    encounter_dx: list[EncounterDiagnosis] | None = None,
) -> CodingAnalysis:
    """Run all detectors over the chart context and return de-duplicated suggestions.

    Supply either ``facts`` (a snapshot facts dict — its single lab is read) and/or an explicit
    ``lab_values`` map (canonical marker → value) for a fuller encounter view; the two are
    merged, with ``lab_values`` taking precedence. Enforces the no-evidence-no-suggestion
    guardrail and returns a deterministic ordering so persistence is stable.
    """
    problem_list = problem_list or []
    encounter_dx = encounter_dx or []
    merged: dict[str, float] = {}
    if facts:
        merged.update(lab_values_from_facts(facts))
    if lab_values:
        merged.update({str(k): float(v) for k, v in lab_values.items()})

    found: list[CodingSuggestion] = []
    found += detect_documented_uncoded(problem_list, encounter_dx)
    found += detect_hcc_gaps(merged, problem_list, encounter_dx)
    found += detect_specificity_upgrades(merged, encounter_dx)

    # Guardrail: every suggestion MUST be evidence-linked. An evidence-less suggestion is a
    # bug in a detector, not a claim we would ever surface — drop it and fail tests.
    evidenced = [s for s in found if s.evidence]
    assert len(evidenced) == len(found), "coding suggestion produced without evidence"

    # De-duplicate (idempotent re-analysis) and order deterministically.
    unique: dict[str, CodingSuggestion] = {}
    for s in evidenced:
        unique.setdefault(s.dedup_key, s)
    ordered = sorted(
        unique.values(),
        key=lambda s: (_TYPE_ORDER[s.suggestion_type], s.icd10_code, s.supersedes_code or ""),
    )
    return CodingAnalysis(suggestions=tuple(ordered))


_TYPE_ORDER = {
    SuggestionType.HCC_GAP: 0,
    SuggestionType.SPECIFICITY_UPGRADE: 1,
    SuggestionType.DOCUMENTED_UNCODED: 2,
}


__all__ = [
    "SuggestionType", "ProblemListItem", "EncounterDiagnosis", "CodingSuggestion",
    "CodingAnalysis", "analyze", "detect_documented_uncoded", "detect_hcc_gaps",
    "detect_specificity_upgrades", "lab_values_from_facts",
]
