"""Deterministic UCUM unit normalization (plan Phase 1, workstream 2).

Every marker has one canonical unit. Inbound values in a recognised alternate unit are
converted with a fixed, tested factor. A unit that is neither canonical nor a recognised
alternate raises ``UnsupportedUnitError`` — which the pipeline turns into an ``Unsupported``
classification that BLOCKS interpretation (spec §6.1.6). We never guess a conversion.

Conversions are pure functions of value only, so they are trivially unit-testable and
replay-deterministic.
"""
from __future__ import annotations

from collections.abc import Callable

from .markers import MARKER_SPECS, CanonicalMarker


class UnsupportedUnitError(ValueError):
    """Raised when a marker's unit cannot be safely converted to canonical."""

    def __init__(self, marker: CanonicalMarker, unit: str) -> None:
        self.marker = marker
        self.unit = unit
        super().__init__(f"unsupported unit {unit!r} for marker {marker.value}")


def _norm(unit: str | None) -> str:
    """Normalise a unit token for matching: lowercase, strip spaces and surrounding braces."""
    if unit is None:
        return ""
    return unit.strip().lower().replace(" ", "").replace("{", "").replace("}", "")


# Per-marker converters keyed by normalised alternate unit -> callable(value)->canonical value.
# The canonical unit itself is always accepted as identity and need not be listed.
_CONVERTERS: dict[CanonicalMarker, dict[str, Callable[[float], float]]] = {
    # A1c: IFCC mmol/mol -> NGSP % (NGSP = 0.09148*IFCC + 2.152).
    CanonicalMarker.HEMOGLOBIN_A1C: {
        "mmol/mol": lambda v: 0.09148 * v + 2.152,
    },
    # Glucose: mmol/L -> mg/dL (x18.0182).
    CanonicalMarker.GLUCOSE: {
        "mmol/l": lambda v: v * 18.0182,
    },
    # Creatinine: umol/L -> mg/dL (/88.42).
    CanonicalMarker.CREATININE: {
        "umol/l": lambda v: v / 88.42,
        "µmol/l": lambda v: v / 88.42,
    },
    # eGFR: alternate spelling of the canonical unit only.
    CanonicalMarker.EGFR: {
        "ml/min/1.73_m2": lambda v: v,
        "ml/min": lambda v: v,
    },
    # Potassium: mEq/L == mmol/L for a monovalent ion.
    CanonicalMarker.POTASSIUM: {
        "meq/l": lambda v: v,
    },
    # LDL: mmol/L -> mg/dL (x38.67).
    CanonicalMarker.LDL_CHOLESTEROL: {
        "mmol/l": lambda v: v * 38.67,
    },
}


def to_canonical_unit(marker: CanonicalMarker, value: float, unit: str | None) -> float:
    """Convert ``value`` in ``unit`` to the marker's canonical unit.

    Raises ``UnsupportedUnitError`` if the unit is unknown for this marker — the caller
    must then block interpretation rather than proceed with an unsafe value.
    """
    canonical = _norm(MARKER_SPECS[marker].canonical_unit)
    given = _norm(unit)
    if given == canonical:
        return float(value)
    converter = _CONVERTERS.get(marker, {}).get(given)
    if converter is None:
        raise UnsupportedUnitError(marker, unit or "")
    return float(converter(float(value)))
