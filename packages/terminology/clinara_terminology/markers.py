"""Canonical marker catalog and the seed LOINC map (plan Phase 1 + Phase 10).

Phase 1 shipped six core metabolic markers. **Phase 10 (Specialty Protocol Breadth, closes
gaps.md G6)** grows the catalog to cover 30+ ambulatory specialties: thyroid, extended
lipids, hepatic panel, hematology, coagulation, inflammatory, and electrolyte markers. Every
marker declares its canonical unit, a default reference range used for classification when
the payload omits one, and the ``fact_alias`` the protocol engine publishes its primary
value under (e.g. ``lab.a1c``) so rules read against friendly names.

Adding a marker here is a **pure data change** — no engine edit. ``LAB_FACT_ALIAS`` (the map
the deterministic engine reasons over) is *derived* from this catalog rather than hand-kept
in the engine, so specialty breadth scales without touching the crown-jewel evaluator (plan
Phase 10: "content/validation effort, not engine work").

Reference ranges here are *defaults for classification only*. They are NOT the critical
thresholds — those live in ``clinara_protocol_engine.critical`` and are hard-coded so no
client or clinician configuration can weaken them (spec §6.1.6).
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class CanonicalMarker(str, Enum):
    # --- Phase 1 core metabolic markers ---
    HEMOGLOBIN_A1C = "hemoglobin_a1c"
    GLUCOSE = "glucose"
    CREATININE = "creatinine"
    EGFR = "egfr"
    POTASSIUM = "potassium"
    LDL_CHOLESTEROL = "ldl_cholesterol"
    # --- Phase 10 breadth: thyroid ---
    TSH = "tsh"
    FREE_T4 = "free_t4"
    # --- Phase 10 breadth: extended lipids / cardiometabolic ---
    HDL_CHOLESTEROL = "hdl_cholesterol"
    TRIGLYCERIDES = "triglycerides"
    TOTAL_CHOLESTEROL = "total_cholesterol"
    # --- Phase 10 breadth: hepatic panel ---
    ALT = "alt"
    AST = "ast"
    TOTAL_BILIRUBIN = "total_bilirubin"
    ALKALINE_PHOSPHATASE = "alkaline_phosphatase"
    # --- Phase 10 breadth: hematology ---
    HEMOGLOBIN = "hemoglobin"
    PLATELETS = "platelets"
    WBC = "wbc"
    # --- Phase 10 breadth: coagulation ---
    INR = "inr"
    # --- Phase 10 breadth: inflammatory ---
    CRP = "crp"
    ESR = "esr"
    # --- Phase 10 breadth: electrolytes / renal ---
    SODIUM = "sodium"
    CALCIUM = "calcium"
    BUN = "bun"


@dataclass(frozen=True)
class MarkerSpec:
    marker: CanonicalMarker
    canonical_unit: str
    # Default reference interval (inclusive) for classification; None = unbounded on that side.
    ref_low: float | None
    ref_high: float | None
    display_name: str
    # The fact name the engine publishes this marker's primary value under (e.g. ``lab.a1c``).
    fact_alias: str


def _spec(marker: CanonicalMarker, unit: str, ref_low: float | None,
          ref_high: float | None, display_name: str, alias: str) -> MarkerSpec:
    return MarkerSpec(marker, unit, ref_low, ref_high, display_name, alias)


MARKER_SPECS: dict[CanonicalMarker, MarkerSpec] = {
    # --- Phase 1 core ---
    CanonicalMarker.HEMOGLOBIN_A1C: _spec(
        CanonicalMarker.HEMOGLOBIN_A1C, "%", None, 5.7, "Hemoglobin A1c", "lab.a1c"),
    CanonicalMarker.GLUCOSE: _spec(
        CanonicalMarker.GLUCOSE, "mg/dL", 70.0, 99.0, "Glucose", "lab.glucose"),
    CanonicalMarker.CREATININE: _spec(
        CanonicalMarker.CREATININE, "mg/dL", 0.6, 1.3, "Creatinine", "lab.creatinine"),
    CanonicalMarker.EGFR: _spec(
        CanonicalMarker.EGFR, "mL/min/1.73m2", 60.0, None, "eGFR", "lab.egfr"),
    CanonicalMarker.POTASSIUM: _spec(
        CanonicalMarker.POTASSIUM, "mmol/L", 3.5, 5.1, "Potassium", "lab.potassium"),
    CanonicalMarker.LDL_CHOLESTEROL: _spec(
        CanonicalMarker.LDL_CHOLESTEROL, "mg/dL", None, 130.0, "LDL cholesterol", "lab.ldl"),
    # --- Phase 10: thyroid ---
    CanonicalMarker.TSH: _spec(
        CanonicalMarker.TSH, "mIU/L", 0.4, 4.5, "TSH", "lab.tsh"),
    CanonicalMarker.FREE_T4: _spec(
        CanonicalMarker.FREE_T4, "ng/dL", 0.8, 1.8, "Free T4", "lab.free_t4"),
    # --- Phase 10: extended lipids ---
    CanonicalMarker.HDL_CHOLESTEROL: _spec(
        CanonicalMarker.HDL_CHOLESTEROL, "mg/dL", 40.0, None, "HDL cholesterol", "lab.hdl"),
    CanonicalMarker.TRIGLYCERIDES: _spec(
        CanonicalMarker.TRIGLYCERIDES, "mg/dL", None, 150.0, "Triglycerides",
        "lab.triglycerides"),
    CanonicalMarker.TOTAL_CHOLESTEROL: _spec(
        CanonicalMarker.TOTAL_CHOLESTEROL, "mg/dL", None, 200.0, "Total cholesterol",
        "lab.total_cholesterol"),
    # --- Phase 10: hepatic panel ---
    CanonicalMarker.ALT: _spec(
        CanonicalMarker.ALT, "U/L", None, 40.0, "ALT", "lab.alt"),
    CanonicalMarker.AST: _spec(
        CanonicalMarker.AST, "U/L", None, 40.0, "AST", "lab.ast"),
    CanonicalMarker.TOTAL_BILIRUBIN: _spec(
        CanonicalMarker.TOTAL_BILIRUBIN, "mg/dL", None, 1.2, "Total bilirubin",
        "lab.total_bilirubin"),
    CanonicalMarker.ALKALINE_PHOSPHATASE: _spec(
        CanonicalMarker.ALKALINE_PHOSPHATASE, "U/L", 44.0, 147.0, "Alkaline phosphatase",
        "lab.alk_phos"),
    # --- Phase 10: hematology ---
    CanonicalMarker.HEMOGLOBIN: _spec(
        CanonicalMarker.HEMOGLOBIN, "g/dL", 12.0, 17.5, "Hemoglobin", "lab.hemoglobin"),
    CanonicalMarker.PLATELETS: _spec(
        CanonicalMarker.PLATELETS, "10^9/L", 150.0, 400.0, "Platelets", "lab.platelets"),
    CanonicalMarker.WBC: _spec(
        CanonicalMarker.WBC, "10^9/L", 4.0, 11.0, "White blood cell count", "lab.wbc"),
    # --- Phase 10: coagulation ---
    CanonicalMarker.INR: _spec(
        CanonicalMarker.INR, "ratio", 0.8, 1.2, "INR", "lab.inr"),
    # --- Phase 10: inflammatory ---
    CanonicalMarker.CRP: _spec(
        CanonicalMarker.CRP, "mg/L", None, 3.0, "C-reactive protein", "lab.crp"),
    CanonicalMarker.ESR: _spec(
        CanonicalMarker.ESR, "mm/hr", None, 20.0, "Erythrocyte sedimentation rate", "lab.esr"),
    # --- Phase 10: electrolytes / renal ---
    CanonicalMarker.SODIUM: _spec(
        CanonicalMarker.SODIUM, "mmol/L", 135.0, 145.0, "Sodium", "lab.sodium"),
    CanonicalMarker.CALCIUM: _spec(
        CanonicalMarker.CALCIUM, "mg/dL", 8.5, 10.2, "Calcium", "lab.calcium"),
    CanonicalMarker.BUN: _spec(
        CanonicalMarker.BUN, "mg/dL", 7.0, 20.0, "Blood urea nitrogen", "lab.bun"),
}


# The engine reasons over facts by their alias. Derived from the catalog so adding a marker
# is a pure data change (Phase 10) — the engine imports this rather than hand-maintaining it.
LAB_FACT_ALIAS: dict[CanonicalMarker, str] = {
    marker: spec.fact_alias for marker, spec in MARKER_SPECS.items()
}


# Seed LOINC -> canonical marker map. Real deployments extend this per tenant via the
# IntegrationMapping table; unknown codes are queued, never guessed (spec §6.1.6).
LOINC_MAP: dict[str, CanonicalMarker] = {
    # Hemoglobin A1c
    "4548-4": CanonicalMarker.HEMOGLOBIN_A1C,
    "4549-2": CanonicalMarker.HEMOGLOBIN_A1C,
    "17856-6": CanonicalMarker.HEMOGLOBIN_A1C,
    # Glucose
    "2345-7": CanonicalMarker.GLUCOSE,
    "2339-0": CanonicalMarker.GLUCOSE,
    # Creatinine
    "2160-0": CanonicalMarker.CREATININE,
    # eGFR
    "33914-3": CanonicalMarker.EGFR,
    "62238-1": CanonicalMarker.EGFR,
    # Potassium
    "2823-3": CanonicalMarker.POTASSIUM,
    "6298-4": CanonicalMarker.POTASSIUM,
    # LDL cholesterol
    "13457-7": CanonicalMarker.LDL_CHOLESTEROL,
    "18262-6": CanonicalMarker.LDL_CHOLESTEROL,
    "2089-1": CanonicalMarker.LDL_CHOLESTEROL,
    # --- Phase 10 breadth ---
    # TSH
    "3016-3": CanonicalMarker.TSH,
    "11579-0": CanonicalMarker.TSH,
    # Free T4
    "3024-7": CanonicalMarker.FREE_T4,
    # HDL cholesterol
    "2085-9": CanonicalMarker.HDL_CHOLESTEROL,
    # Triglycerides
    "2571-8": CanonicalMarker.TRIGLYCERIDES,
    # Total cholesterol
    "2093-3": CanonicalMarker.TOTAL_CHOLESTEROL,
    # ALT
    "1742-6": CanonicalMarker.ALT,
    # AST
    "1920-8": CanonicalMarker.AST,
    # Total bilirubin
    "1975-2": CanonicalMarker.TOTAL_BILIRUBIN,
    # Alkaline phosphatase
    "6768-6": CanonicalMarker.ALKALINE_PHOSPHATASE,
    # Hemoglobin
    "718-7": CanonicalMarker.HEMOGLOBIN,
    # Platelets
    "777-3": CanonicalMarker.PLATELETS,
    # WBC
    "6690-2": CanonicalMarker.WBC,
    # INR
    "6301-6": CanonicalMarker.INR,
    "34714-6": CanonicalMarker.INR,
    # CRP
    "1988-5": CanonicalMarker.CRP,
    "30522-7": CanonicalMarker.CRP,
    # ESR
    "4537-7": CanonicalMarker.ESR,
    # Sodium
    "2951-2": CanonicalMarker.SODIUM,
    # Calcium
    "17861-6": CanonicalMarker.CALCIUM,
    # BUN
    "3094-0": CanonicalMarker.BUN,
}
