"""Pure analytics & personalization core (plan Phase 6, testing focus).

Runs with PYTHONPATH=apps/api, Django-free. Proves the safety invariants: personalization
can never touch a safety-protected field, cross-tenant data is de-identified + small cells
suppressed, and aggregation is correct.
"""
import pytest

from domains.analytics import core


# ---- Edit-difference + aggregation ----

def test_edit_difference_detects_shortening():
    diff = core.edit_difference("the quick brown fox jumps", "the fox jumps")
    assert diff.shortened is True
    assert diff.length_delta == -2
    assert "quick" in diff.removed_words


def test_aggregate_feedback_rates():
    m = core.aggregate_feedback(["approve", "approve", "edit", "override", "escalate"])
    assert m.total == 5
    assert m.agreement_rate == 0.4
    assert m.override_rate == 0.2


# ---- Preference derivation + safety guard ----

def test_derive_preference_from_consistent_shortening():
    edits = [core.edit_difference("a b c d e", "a b") for _ in range(3)]
    signal = core.derive_preferences("dr_smith", edits)
    assert signal is not None
    assert signal.adjustments == {"verbosity": "concise"}


def test_derive_preference_needs_enough_observations():
    edits = [core.edit_difference("a b c d", "a b")]
    assert core.derive_preferences("dr_smith", edits, min_observations=3) is None


def test_preference_cannot_touch_safety_field():
    with pytest.raises(core.PreferenceSafetyViolation):
        core.assert_preference_safe({"critical_threshold": 6.0})
    with pytest.raises(core.PreferenceSafetyViolation):
        core.assert_preference_safe({"required_warning": "removed"})
    with pytest.raises(core.PreferenceSafetyViolation):
        core.assert_preference_safe({"automation_status": "full_auto"})


def test_preference_allows_low_risk_fields():
    core.assert_preference_safe({"verbosity": "concise", "tone": "warmer"})  # no raise


def test_recommendation_is_inert_data():
    edits = [core.edit_difference("a b c d e", "a b") for _ in range(4)]
    signal = core.derive_preferences("dr_x", edits)
    rec = core.recommend_from_signal(signal, target="results_template")
    # A recommendation is pure data carrying the proposal + rationale — it takes no action.
    assert rec.proposal["adjustments"] == {"verbosity": "concise"}
    assert rec.supporting_observations == 4


# ---- Privacy controls ----

def test_small_cells_are_suppressed():
    cells = core.suppress_small_cells({"cohort_a": 3, "cohort_b": 50}, min_cell=11)
    assert cells["cohort_a"] == "suppressed"
    assert cells["cohort_b"] == 50


def test_deidentify_strips_direct_identifiers():
    row = {"patient_external_id": "P1", "actor": "dr_smith", "agreement_rate": 0.9}
    clean = core.deidentify(row)
    assert "patient_external_id" not in clean
    assert "actor" not in clean
    assert clean["agreement_rate"] == 0.9
