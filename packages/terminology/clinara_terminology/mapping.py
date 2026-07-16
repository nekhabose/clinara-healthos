"""Code mapping + normalization entry points (plan Phase 1, workstream 2).

``map_code`` resolves a vendor code (LOINC in the seed set) to a canonical marker, or
raises ``UnknownCodeError`` so the caller can park the event on the unknown-code queue —
nothing is silently dropped (plan §1.1 invariant 2).

``normalize_result`` combines mapping + unit conversion and returns a
``NormalizedResult`` the context builder can consume.
"""
from __future__ import annotations

from dataclasses import dataclass

from .markers import LOINC_MAP, MARKER_SPECS, CanonicalMarker
from .units import UnsupportedUnitError, to_canonical_unit


class UnknownCodeError(KeyError):
    """Raised when a (system, code) pair has no canonical mapping."""

    def __init__(self, system: str, code: str) -> None:
        self.system = system
        self.code = code
        super().__init__(f"unmapped code {system}:{code}")


@dataclass(frozen=True)
class NormalizedResult:
    marker: CanonicalMarker
    value: float
    canonical_unit: str
    original_value: float
    original_unit: str | None


def map_code(system: str, code: str) -> CanonicalMarker:
    """Resolve a vendor code to a canonical marker. Raises ``UnknownCodeError`` if unmapped."""
    if system.strip().upper() == "LOINC":
        marker = LOINC_MAP.get(code.strip())
        if marker is not None:
            return marker
    raise UnknownCodeError(system, code)


def normalize_result(
    system: str, code: str, value: float, unit: str | None
) -> NormalizedResult:
    """Map + unit-normalize a raw result.

    Propagates ``UnknownCodeError`` (queue it) and ``UnsupportedUnitError`` (block
    interpretation) so the pipeline can apply the correct safety behaviour for each.
    """
    marker = map_code(system, code)
    canonical_value = to_canonical_unit(marker, value, unit)
    return NormalizedResult(
        marker=marker,
        value=canonical_value,
        canonical_unit=MARKER_SPECS[marker].canonical_unit,
        original_value=float(value),
        original_unit=unit,
    )


__all__ = [
    "CanonicalMarker",
    "NormalizedResult",
    "UnknownCodeError",
    "UnsupportedUnitError",
    "map_code",
    "normalize_result",
]
