"""Critical thresholds + operators (plan Phase 1 — the un-weakenable safety floor)."""
import pytest

from clinara_protocol_engine import apply_operator, critical_breach
from clinara_protocol_engine.operators import UnknownOperatorError
from clinara_terminology import CanonicalMarker


@pytest.mark.parametrize(
    "marker,value,expected",
    [
        (CanonicalMarker.POTASSIUM, 6.1, "POTASSIUM_CRITICAL_HIGH"),
        (CanonicalMarker.POTASSIUM, 2.4, "POTASSIUM_CRITICAL_LOW"),
        (CanonicalMarker.POTASSIUM, 4.2, None),
        (CanonicalMarker.GLUCOSE, 501, "GLUCOSE_CRITICAL_HIGH"),
        (CanonicalMarker.GLUCOSE, 49, "GLUCOSE_CRITICAL_LOW"),
        (CanonicalMarker.EGFR, 14, "EGFR_CRITICAL_LOW"),
        (CanonicalMarker.EGFR, 200, None),  # no critical-high for eGFR
        (CanonicalMarker.LDL_CHOLESTEROL, 400, None),  # no critical band defined
    ],
)
def test_critical_breach(marker, value, expected):
    assert critical_breach(marker, value) == expected


def test_potassium_boundary_is_not_critical():
    # Exactly at the limit is NOT a breach (strict inequality) — documents the boundary.
    assert critical_breach(CanonicalMarker.POTASSIUM, 6.0) is None
    assert critical_breach(CanonicalMarker.POTASSIUM, 2.5) is None


def test_operators():
    assert apply_operator("greater_than_or_equal", 7.0, 7.0) is True
    assert apply_operator("less_than", 9.0, 9.0) is False
    assert apply_operator("equals", True, True) is True
    assert apply_operator("in", "a", ["a", "b"]) is True
    with pytest.raises(UnknownOperatorError):
        apply_operator("regex_match", "x", "y")


def test_numeric_operator_rejects_boolean():
    # Guards against a YAML author comparing a boolean fact with a numeric operator.
    with pytest.raises(TypeError):
        apply_operator("greater_than", True, 1)
