"""Clinical coding catalog — the deterministic content the coding engine reasons over
(plan Phase 9 — closes G1).

This mirrors the invariant in ``gaps.md §1`` and ``plan.md §1``: the revenue-integrity
module is **deterministic, evidence-based, and human-confirmed** — never a generative or
probabilistic coder. The catalog here is the codified clinical logic (thresholds → codes),
exactly the way ``clinara_terminology.MARKER_SPECS`` codifies lab thresholds. It is data,
not model output, so every suggestion it drives is replayable and testable.

Scope note: the ICD-10 codes and HCC category tags below are a **seed, illustrative**
catalog covering the six Phase-1 lab markers' downstream conditions (diabetes, chronic
kidney disease). Real deployments extend it per specialty through the same governed
authoring path as protocols (plan Phase 10). The HCC tags follow the CMS-HCC
risk-adjustment model's category structure; they are labelled illustratively and are
configurable — the point is the deterministic, evidence-linked pipeline, not a certified
crosswalk (which is versioned by CMS annually and owned by clinical/coding staff).
"""
from __future__ import annotations

from dataclasses import dataclass

from clinara_terminology import CanonicalMarker


@dataclass(frozen=True)
class Icd10Code:
    code: str
    description: str
    # An HCC (Hierarchical Condition Category) tag when the code is risk-adjustable, else
    # None. Presence of a tag is what makes a gap an "HCC gap" vs a plain documentation gap.
    hcc: str | None = None


# --------------------------------------------------------------------------------------
# Diabetes mellitus (type 2) — A1c-driven
# --------------------------------------------------------------------------------------

# ADA diagnostic threshold for diabetes (%). At/above this a documented diagnosis is
# clinically supported; below it we NEVER suggest a diabetes code (negative case).
A1C_DIABETES_THRESHOLD = 6.5

DIABETES_UNSPECIFIED = Icd10Code(
    "E11.9", "Type 2 diabetes mellitus without complications", hcc="HCC-38 (Diabetes)"
)
# Specificity upgrade target when diabetes co-occurs with CKD (a diabetic complication).
DIABETES_WITH_CKD = Icd10Code(
    "E11.22", "Type 2 diabetes mellitus with diabetic chronic kidney disease",
    hcc="HCC-37 (Diabetes with Chronic Complications)",
)


# --------------------------------------------------------------------------------------
# Chronic kidney disease — eGFR-driven staging (KDIGO)
# --------------------------------------------------------------------------------------

# CKD is only coded when eGFR indicates stage 3 or worse (< 60). Stages 1–2 require
# albuminuria / structural markers we do not carry, so at eGFR >= 60 we suggest NOTHING
# (negative case — a conservative anti-upcoding floor).
CKD_STAGE_FLOOR = 60.0


@dataclass(frozen=True)
class CkdStage:
    low_inclusive: float  # eGFR >= low
    high_exclusive: float  # eGFR <  high
    code: Icd10Code


# Ordered, non-overlapping eGFR bands → specific CKD stage code. HCC tags on stages 4–5
# (and unspecified/severe) reflect their risk-adjustment weight; stage 3 is a documentation
# gap without an HCC tag here.
CKD_STAGES: tuple[CkdStage, ...] = (
    CkdStage(0.0, 15.0, Icd10Code("N18.5", "Chronic kidney disease, stage 5",
                                  hcc="HCC-326 (CKD Stage 5)")),
    CkdStage(15.0, 30.0, Icd10Code("N18.4", "Chronic kidney disease, stage 4 (severe)",
                                   hcc="HCC-327 (CKD Stage 4)")),
    CkdStage(30.0, 45.0, Icd10Code("N18.32", "Chronic kidney disease, stage 3b")),
    CkdStage(45.0, 60.0, Icd10Code("N18.31", "Chronic kidney disease, stage 3a")),
)

# Unspecified CKD code eligible for an eGFR-driven specificity upgrade.
CKD_UNSPECIFIED_CODE = "N18.9"


def ckd_stage_for_egfr(egfr: float) -> Icd10Code | None:
    """Return the specific CKD stage code for an eGFR, or None if eGFR >= 60 (no CKD floor).

    Deterministic and total: every eGFR maps to exactly one band or to None. No suggestion
    is produced above the stage-3 floor, which is the conservative anti-upcoding behaviour.
    """
    if egfr >= CKD_STAGE_FLOOR:
        return None
    for stage in CKD_STAGES:
        if stage.low_inclusive <= egfr < stage.high_exclusive:
            return stage.code
    return None


# --------------------------------------------------------------------------------------
# HCC lookup for arbitrary documented-but-uncoded problems
# --------------------------------------------------------------------------------------

# Minimal seed crosswalk: ICD-10 (uppercased, dot-stripped prefix match) → HCC tag. Used to
# tag a documented-but-uncoded problem as risk-adjustable. Extended via the governed catalog.
_HCC_BY_CODE: dict[str, str] = {
    "E1122": DIABETES_WITH_CKD.hcc or "",
    "E11": "HCC-38 (Diabetes)",
    "N185": "HCC-326 (CKD Stage 5)",
    "N184": "HCC-327 (CKD Stage 4)",
    "I50": "HCC-226 (Heart Failure)",
    "J44": "HCC-280 (COPD)",
}


def _normalize_code(code: str) -> str:
    return code.replace(".", "").replace(" ", "").upper()


def hcc_for_code(code: str) -> str | None:
    """Longest-prefix HCC tag for an ICD-10 code, or None. Prefix match so ``E11.22`` and
    ``E11.9`` both resolve without enumerating every leaf."""
    norm = _normalize_code(code)
    best: str | None = None
    best_len = 0
    for prefix, hcc in _HCC_BY_CODE.items():
        if norm.startswith(prefix) and len(prefix) > best_len:
            best, best_len = hcc, len(prefix)
    return best


# Marker string aliases used when reading canonical lab facts.
MARKER_A1C = CanonicalMarker.HEMOGLOBIN_A1C.value
MARKER_EGFR = CanonicalMarker.EGFR.value
