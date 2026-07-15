"""Clinara terminology: LOINC/UCUM mapping and unit normalization (plan Phase 1).

Deterministic, tested conversions. Unknown codes and unsupported units are surfaced as
typed errors so the pipeline can queue or block them — never guess (spec §6.1.6).
"""

from .mapping import (
    NormalizedResult,
    UnknownCodeError,
    UnsupportedUnitError,
    map_code,
    normalize_result,
)
from .markers import (
    LOINC_MAP,
    MARKER_SPECS,
    CanonicalMarker,
    MarkerSpec,
)
from .medications import (
    LOW_RISK_REFILL_CLASSES,
    MEDICATION_SPECS,
    ControlledSchedule,
    MedicationClass,
    MedicationSpec,
    UnknownMedicationError,
    map_medication,
)
from .units import to_canonical_unit

__all__ = [
    "CanonicalMarker",
    "MarkerSpec",
    "MARKER_SPECS",
    "LOINC_MAP",
    "NormalizedResult",
    "UnknownCodeError",
    "UnsupportedUnitError",
    "map_code",
    "normalize_result",
    "to_canonical_unit",
    # Phase 4 — medications
    "MedicationClass",
    "ControlledSchedule",
    "MedicationSpec",
    "MEDICATION_SPECS",
    "UnknownMedicationError",
    "map_medication",
    "LOW_RISK_REFILL_CLASSES",
]
