"""Phase 10 — Specialty Protocol Breadth catalog expansion (closes gaps.md G6).

The catalog grows from 6 markers to 25 across ambulatory specialties, and ``LAB_FACT_ALIAS``
is now DERIVED from the catalog (so adding a marker is a pure data change — no engine edit).
"""
import pytest

from clinara_terminology import (
    LAB_FACT_ALIAS,
    MARKER_SPECS,
    CanonicalMarker,
    UnsupportedUnitError,
    to_canonical_unit,
)


def test_catalog_covers_the_new_specialty_markers():
    for marker in (
        CanonicalMarker.TSH, CanonicalMarker.FREE_T4, CanonicalMarker.HDL_CHOLESTEROL,
        CanonicalMarker.TRIGLYCERIDES, CanonicalMarker.TOTAL_CHOLESTEROL,
        CanonicalMarker.ALT, CanonicalMarker.AST, CanonicalMarker.TOTAL_BILIRUBIN,
        CanonicalMarker.ALKALINE_PHOSPHATASE, CanonicalMarker.HEMOGLOBIN,
        CanonicalMarker.PLATELETS, CanonicalMarker.WBC, CanonicalMarker.INR,
        CanonicalMarker.CRP, CanonicalMarker.ESR, CanonicalMarker.SODIUM,
        CanonicalMarker.CALCIUM, CanonicalMarker.BUN,
    ):
        assert marker in MARKER_SPECS
        assert MARKER_SPECS[marker].fact_alias.startswith("lab.")


def test_lab_fact_alias_is_derived_from_the_catalog():
    # Exactly the catalog's markers, exactly the specs' declared aliases — no drift possible.
    assert set(LAB_FACT_ALIAS) == set(MARKER_SPECS)
    for marker, spec in MARKER_SPECS.items():
        assert LAB_FACT_ALIAS[marker] == spec.fact_alias


def test_phase1_aliases_are_preserved_exactly():
    assert LAB_FACT_ALIAS[CanonicalMarker.HEMOGLOBIN_A1C] == "lab.a1c"
    assert LAB_FACT_ALIAS[CanonicalMarker.LDL_CHOLESTEROL] == "lab.ldl"


@pytest.mark.parametrize(
    "marker,value,unit,expected",
    [
        (CanonicalMarker.TOTAL_CHOLESTEROL, 5.0, "mmol/L", 5.0 * 38.67),
        (CanonicalMarker.TRIGLYCERIDES, 2.0, "mmol/L", 2.0 * 88.57),
        (CanonicalMarker.CALCIUM, 2.5, "mmol/L", 2.5 * 4.008),
        (CanonicalMarker.HEMOGLOBIN, 130.0, "g/L", 13.0),
        (CanonicalMarker.TSH, 3.1, "uIU/mL", 3.1),  # alternate notation, identity magnitude
    ],
)
def test_alternate_units_convert_deterministically(marker, value, unit, expected):
    assert to_canonical_unit(marker, value, unit) == pytest.approx(expected)


def test_unknown_unit_still_raises_never_guesses():
    with pytest.raises(UnsupportedUnitError):
        to_canonical_unit(CanonicalMarker.TSH, 3.0, "banana/L")
