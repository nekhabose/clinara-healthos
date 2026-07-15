"""Pure canonicalization + historical comparison (plan Phase 1, workstreams 2-3).

Django-free so it is unit-testable in isolation and reusable by workers. ``services.py``
wraps this with persistence, audit, and event publishing. Vendor payloads become the
canonical model here; unknown codes and unsupported units are surfaced as flags so the
caller applies the correct "never silently drop" behaviour (plan §1.1 invariant 2).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from clinara_terminology import (
    MARKER_SPECS,
    CanonicalMarker,
    UnknownCodeError,
    UnsupportedUnitError,
    normalize_result,
    to_canonical_unit,
)


@dataclass(frozen=True)
class CanonicalObservation:
    system: str
    code: str
    observed_at: datetime
    original_value: float
    original_unit: str | None
    marker: CanonicalMarker | None = None
    value: float | None = None            # canonical-unit value
    canonical_unit: str | None = None
    unknown_code: bool = False
    unsupported_unit: bool = False

    @property
    def is_usable(self) -> bool:
        return self.marker is not None and self.value is not None


def canonicalize(
    *, system: str, code: str, value: float, unit: str | None, observed_at: datetime,
    resolved_marker: CanonicalMarker | None = None,
) -> CanonicalObservation:
    """Normalize one raw result to canonical marker + unit.

    Returns a ``CanonicalObservation`` with flags rather than raising: the pipeline needs
    to keep the raw event and route it (unknown-code queue / unsupported → block), not
    lose it.

    ``resolved_marker`` lets the caller supply a marker resolved via a **tenant-specific**
    mapping (spec §6.7 — tenant-specific mappings), bypassing the seed LOINC map so a
    locally-mapped code is normalized instead of queued as unknown.
    """
    if resolved_marker is not None:
        try:
            canonical_value = to_canonical_unit(resolved_marker, value, unit)
        except UnsupportedUnitError:
            return CanonicalObservation(
                system=system, code=code, observed_at=observed_at,
                original_value=float(value), original_unit=unit,
                marker=resolved_marker, unsupported_unit=True,
            )
        return CanonicalObservation(
            system=system, code=code, observed_at=observed_at,
            original_value=float(value), original_unit=unit,
            marker=resolved_marker, value=canonical_value,
            canonical_unit=MARKER_SPECS[resolved_marker].canonical_unit,
        )
    try:
        normalized = normalize_result(system, code, value, unit)
    except UnknownCodeError:
        return CanonicalObservation(
            system=system, code=code, observed_at=observed_at,
            original_value=float(value), original_unit=unit, unknown_code=True,
        )
    except UnsupportedUnitError as exc:
        return CanonicalObservation(
            system=system, code=code, observed_at=observed_at,
            original_value=float(value), original_unit=unit,
            marker=exc.marker, unsupported_unit=True,
        )
    return CanonicalObservation(
        system=system, code=code, observed_at=observed_at,
        original_value=float(value), original_unit=unit,
        marker=normalized.marker, value=normalized.value,
        canonical_unit=normalized.canonical_unit,
    )


def compute_trend(current: float | None, prior: float | None, *, epsilon: float = 1e-9) -> str:
    """Deterministic trend label from stored canonical history (spec §6.1.3)."""
    if current is None or prior is None:
        return "unknown"
    delta = float(current) - float(prior)
    if abs(delta) <= epsilon:
        return "stable"
    return "rising" if delta > 0 else "falling"
