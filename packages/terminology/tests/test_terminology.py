"""Terminology mapping + deterministic unit normalization (plan Phase 1, workstream 2)."""
import math

import pytest

from clinara_terminology import (
    CanonicalMarker,
    UnknownCodeError,
    UnsupportedUnitError,
    map_code,
    normalize_result,
    to_canonical_unit,
)


def test_maps_known_loinc_codes():
    assert map_code("LOINC", "4548-4") is CanonicalMarker.HEMOGLOBIN_A1C
    assert map_code("loinc", "2823-3") is CanonicalMarker.POTASSIUM  # system is case-insensitive


def test_unknown_code_raises_for_queueing():
    with pytest.raises(UnknownCodeError):
        map_code("LOINC", "0000-0")
    with pytest.raises(UnknownCodeError):
        map_code("CPT", "4548-4")  # right code, wrong system -> not mapped


def test_canonical_unit_is_identity():
    assert to_canonical_unit(CanonicalMarker.POTASSIUM, 4.2, "mmol/L") == 4.2


@pytest.mark.parametrize(
    "marker,value,unit,expected",
    [
        (CanonicalMarker.GLUCOSE, 5.0, "mmol/L", 90.091),         # x18.0182
        (CanonicalMarker.CREATININE, 88.42, "umol/L", 1.0),       # /88.42
        (CanonicalMarker.POTASSIUM, 4.2, "mEq/L", 4.2),           # monovalent identity
        (CanonicalMarker.LDL_CHOLESTEROL, 3.0, "mmol/L", 115.99), # x38.67
        (CanonicalMarker.HEMOGLOBIN_A1C, 53.0, "mmol/mol", 7.0),  # IFCC -> NGSP
    ],
)
def test_unit_conversions_are_deterministic(marker, value, unit, expected):
    assert math.isclose(to_canonical_unit(marker, value, unit), expected, rel_tol=1e-3)


def test_unsupported_unit_raises_to_block_interpretation():
    with pytest.raises(UnsupportedUnitError) as exc:
        to_canonical_unit(CanonicalMarker.GLUCOSE, 5.0, "g/L")
    assert exc.value.marker is CanonicalMarker.GLUCOSE


def test_normalize_result_end_to_end():
    r = normalize_result("LOINC", "2345-7", 5.0, "mmol/L")
    assert r.marker is CanonicalMarker.GLUCOSE
    assert r.canonical_unit == "mg/dL"
    assert math.isclose(r.value, 90.091, rel_tol=1e-3)
    assert r.original_unit == "mmol/L"
