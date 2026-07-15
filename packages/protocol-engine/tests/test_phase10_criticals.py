"""Phase 10 — new critical thresholds for the breadth markers (closes gaps.md G6).

The hard critical floor is extended to the new markers that have conventional adult panic
limits. These run FIRST in the engine and cannot be weakened by any pack rule or per-tenant
threshold — the same non-negotiable guarantee as the Phase 1 markers.
"""
import pytest

from clinara_protocol_engine import critical_breach
from clinara_terminology import CanonicalMarker


@pytest.mark.parametrize(
    "marker,value,expected",
    [
        (CanonicalMarker.SODIUM, 118.0, "SODIUM_CRITICAL_LOW"),
        (CanonicalMarker.SODIUM, 162.0, "SODIUM_CRITICAL_HIGH"),
        (CanonicalMarker.SODIUM, 140.0, None),
        (CanonicalMarker.CALCIUM, 5.5, "CALCIUM_CRITICAL_LOW"),
        (CanonicalMarker.CALCIUM, 14.0, "CALCIUM_CRITICAL_HIGH"),
        (CanonicalMarker.HEMOGLOBIN, 5.0, "HEMOGLOBIN_CRITICAL_LOW"),
        (CanonicalMarker.HEMOGLOBIN, 20.0, None),  # no critical-high for hemoglobin
        (CanonicalMarker.PLATELETS, 15.0, "PLATELETS_CRITICAL_LOW"),
        (CanonicalMarker.WBC, 0.5, "WBC_CRITICAL_LOW"),
        (CanonicalMarker.WBC, 60.0, "WBC_CRITICAL_HIGH"),
        (CanonicalMarker.INR, 6.0, "INR_CRITICAL_HIGH"),
        (CanonicalMarker.INR, 2.5, None),
    ],
)
def test_new_critical_thresholds(marker, value, expected):
    assert critical_breach(marker, value) == expected


def test_markers_without_a_critical_band_return_none():
    # Thyroid / lipids / hepatic markers have no hard panic band — they are protocol-driven.
    for marker in (CanonicalMarker.TSH, CanonicalMarker.ALT, CanonicalMarker.TRIGLYCERIDES):
        assert critical_breach(marker, 9999.0) is None
