"""Canonical marker catalog and the seed LOINC map (plan Phase 1, workstream 2).

Phase 1 supports five core markers for clinical breadth (plan deliverables): A1C, glucose,
creatinine, eGFR, potassium, and LDL. Each marker declares its canonical unit and a
default reference range used for classification when the payload omits one.

Reference ranges here are *defaults for classification only*. They are NOT the critical
thresholds — those live in ``clinara_protocol_engine.critical`` and are hard-coded so no
client or clinician configuration can weaken them (spec §6.1.6).
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class CanonicalMarker(str, Enum):
    HEMOGLOBIN_A1C = "hemoglobin_a1c"
    GLUCOSE = "glucose"
    CREATININE = "creatinine"
    EGFR = "egfr"
    POTASSIUM = "potassium"
    LDL_CHOLESTEROL = "ldl_cholesterol"


@dataclass(frozen=True)
class MarkerSpec:
    marker: CanonicalMarker
    canonical_unit: str
    # Default reference interval (inclusive) for classification; None = unbounded on that side.
    ref_low: float | None
    ref_high: float | None
    display_name: str


MARKER_SPECS: dict[CanonicalMarker, MarkerSpec] = {
    CanonicalMarker.HEMOGLOBIN_A1C: MarkerSpec(
        CanonicalMarker.HEMOGLOBIN_A1C, "%", None, 5.7, "Hemoglobin A1c"
    ),
    CanonicalMarker.GLUCOSE: MarkerSpec(
        CanonicalMarker.GLUCOSE, "mg/dL", 70.0, 99.0, "Glucose"
    ),
    CanonicalMarker.CREATININE: MarkerSpec(
        CanonicalMarker.CREATININE, "mg/dL", 0.6, 1.3, "Creatinine"
    ),
    CanonicalMarker.EGFR: MarkerSpec(
        CanonicalMarker.EGFR, "mL/min/1.73m2", 60.0, None, "eGFR"
    ),
    CanonicalMarker.POTASSIUM: MarkerSpec(
        CanonicalMarker.POTASSIUM, "mmol/L", 3.5, 5.1, "Potassium"
    ),
    CanonicalMarker.LDL_CHOLESTEROL: MarkerSpec(
        CanonicalMarker.LDL_CHOLESTEROL, "mg/dL", None, 130.0, "LDL cholesterol"
    ),
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
}
