"""Hard-coded critical thresholds (spec §6.1.6 — non-negotiable safety floor).

These thresholds are defined in code, evaluated FIRST, and CANNOT be widened or disabled
by any tenant, clinician, or rule configuration (plan §1.1 "two-stage safety on
criticals"). A breach produces a ``CRITICAL_ESCALATION`` that bypasses normal queues and
can never be auto-resolved.

Values are conventional adult critical-result limits in each marker's canonical unit.
They are intentionally NOT read from the database — configurability would defeat the
guarantee.
"""
from __future__ import annotations

from dataclasses import dataclass

from clinara_terminology import CanonicalMarker


@dataclass(frozen=True)
class CriticalRange:
    low: float | None
    high: float | None


# Canonical-unit critical limits. low = panic-low, high = panic-high.
CRITICAL_THRESHOLDS: dict[CanonicalMarker, CriticalRange] = {
    CanonicalMarker.POTASSIUM: CriticalRange(low=2.5, high=6.0),      # mmol/L
    CanonicalMarker.GLUCOSE: CriticalRange(low=50.0, high=500.0),     # mg/dL
    CanonicalMarker.EGFR: CriticalRange(low=15.0, high=None),         # mL/min/1.73m2 (renal failure)
}


def critical_breach(marker: CanonicalMarker, value: float) -> str | None:
    """Return a reason code if ``value`` breaches a critical limit, else ``None``.

    Reason codes are stable, uppercase, and machine-readable for audit/analytics, e.g.
    ``POTASSIUM_CRITICAL_HIGH``.
    """
    rng = CRITICAL_THRESHOLDS.get(marker)
    if rng is None:
        return None
    if rng.low is not None and value < rng.low:
        return f"{marker.value.upper()}_CRITICAL_LOW"
    if rng.high is not None and value > rng.high:
        return f"{marker.value.upper()}_CRITICAL_HIGH"
    return None
