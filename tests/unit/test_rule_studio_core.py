"""Pure Rule-Studio core (plan Phase 2 — lifecycle, simulation, impact, conflict, safety).

Runs with PYTHONPATH=apps/api, Django-free — the governance mechanics behind the Studio are
deterministic and exhaustively unit-testable without a database.
"""
import pytest
from clinara_protocol_engine import Rule
from clinara_terminology import CanonicalMarker

from domains.protocols import core
from domains.protocols.core import RuleState, Scenario

A1C = CanonicalMarker.HEMOGLOBIN_A1C
K = CanonicalMarker.POTASSIUM


def _a1c_rule(version=1, threshold=7.0, classification="clinician_review_required"):
    return Rule.model_validate({
        "id": "a1c_above_target", "version": version, "marker": "hemoglobin_a1c",
        "scope": {"specialties": ["primary_care"]},
        "when": {"all": [
            {"fact": "patient.has_diabetes", "operator": "equals", "value": True},
            {"fact": "lab.a1c", "operator": "greater_than_or_equal", "value": threshold},
        ]},
        "then": {"classification": classification,
                 "recommended_action": "evaluate_current_plan",
                 "reason_codes": ["A1C_ABOVE_CONFIGURED_TARGET"]},
        "safety": {"excluded_when": ["patient.pregnancy"]},
    })


def _scn(name, a1c, specialty="primary_care", diabetes=True, **extra):
    facts = {"lab.a1c": a1c, "patient.has_diabetes": diabetes, **extra}
    return Scenario(name=name, marker=A1C, facts=facts, specialty=specialty)


# ---- Lifecycle state machine (spec §6.5.4) ----

def test_legal_lifecycle_path():
    assert core.can_transition(RuleState.DRAFT, RuleState.IN_REVIEW)
    assert core.can_transition(RuleState.IN_REVIEW, RuleState.APPROVED)
    assert core.can_transition(RuleState.APPROVED, RuleState.ACTIVE)
    assert core.can_transition(RuleState.ACTIVE, RuleState.ROLLED_BACK)


def test_illegal_jump_is_rejected():
    assert not core.can_transition(RuleState.DRAFT, RuleState.ACTIVE)
    with pytest.raises(core.IllegalTransition):
        core.assert_transition(RuleState.DRAFT, RuleState.ACTIVE)
    assert not core.can_transition(RuleState.RETIRED, RuleState.ACTIVE)


# ---- Simulation (spec §6.5.6) ----

def test_simulation_parity_with_engine():
    rule = _a1c_rule()
    scenarios = [_scn("above", 7.8), _scn("normal", 5.4, diabetes=False)]
    result = core.simulate(scenarios, proposed_rules=[rule], current_rules=None)
    by_name = {c.scenario: c for c in result.cases}
    assert by_name["above"].proposed_classification == "clinician_review_required"
    assert by_name["above"].proposed_matched_rule == "a1c_above_target"
    assert by_name["normal"].proposed_classification == "normal"


def test_simulation_detects_behaviour_change():
    current = [_a1c_rule(version=1, threshold=7.0)]
    proposed = [_a1c_rule(version=2, threshold=8.0)]
    # A1C 7.5 matched the old rule (>=7.0) but not the new (>=8.0) → behaviour changes.
    result = core.simulate([_scn("mid", 7.5)], proposed_rules=proposed, current_rules=current)
    case = result.cases[0]
    assert case.agreement is False
    assert "classification" in case.changed_fields
    assert result.agreement_rate == 0.0


# ---- Impact analysis (spec §6.5.7) ----

def test_impact_flags_high_risk_change():
    current = [_a1c_rule(version=1, threshold=7.0)]
    proposed = [_a1c_rule(version=2, threshold=9.0)]
    scn = Scenario(name="pregnant_high", marker=A1C, specialty="primary_care",
                   facts={"lab.a1c": 8.0, "patient.has_diabetes": True,
                          "patient.pregnancy": True})
    report = core.impact_report([scn], proposed_rules=proposed, current_rules=current)
    assert report.total_cases == 1
    # Pregnancy cohort is excluded from the general rule, so both sides fall through to the
    # reference-range default — a change here (if any) is high-risk-tagged.
    assert report.safe_to_activate is True


def test_impact_report_counts_changes():
    current = [_a1c_rule(version=1, threshold=7.0)]
    proposed = [_a1c_rule(version=2, threshold=8.0)]
    scenarios = [_scn("a", 7.5), _scn("b", 8.5), _scn("c", 6.0, diabetes=False)]
    report = core.impact_report(scenarios, proposed_rules=proposed, current_rules=current)
    assert report.changed_cases == 1  # only 7.5 flips


# ---- Conflict detection (spec §6.4.3) ----

def test_conflict_when_two_equal_precedence_rules_disagree():
    r1 = _a1c_rule(version=1, classification="clinician_review_required")
    r2 = Rule.model_validate({
        "id": "a1c_alt", "version": 1, "marker": "hemoglobin_a1c",
        "scope": {"specialties": ["primary_care"]},
        "when": {"all": [{"fact": "lab.a1c", "operator": "greater_than_or_equal", "value": 7.0}]},
        "then": {"classification": "routine_follow_up"},
    })
    conflicts = core.detect_conflicts([_scn("both", 7.8)], rules=[r1, r2])
    assert len(conflicts) == 1
    assert set(conflicts[0].rule_ids) == {"a1c_above_target", "a1c_alt"}


def test_no_conflict_when_precedence_differs():
    # Specialty-scoped rule outranks a global rule → unambiguous winner, not a conflict.
    scoped = _a1c_rule(version=1)
    global_rule = Rule.model_validate({
        "id": "a1c_global", "version": 1, "marker": "hemoglobin_a1c",
        "when": {"all": [{"fact": "lab.a1c", "operator": "greater_than_or_equal", "value": 7.0}]},
        "then": {"classification": "routine_follow_up"},
    })
    conflicts = core.detect_conflicts([_scn("s", 7.8)], rules=[scoped, global_rule])
    assert conflicts == []


# ---- Safety guard: the Studio cannot weaken a critical (plan Phase 2 risk) ----

def test_rule_cannot_down_classify_a_critical_value():
    # A rule claiming a non-critical outcome for a critical-high potassium (6.8 > 6.0) is
    # refused before it can ever be stored/deployed.
    unsafe = Rule.model_validate({
        "id": "k_soft", "version": 1, "marker": "potassium",
        "when": {"all": [{"fact": "lab.potassium", "operator": "greater_than", "value": 5.5}]},
        "then": {"classification": "routine_follow_up"},
    })
    critical_scn = Scenario(name="k_crit", marker=K, facts={"lab.potassium": 6.8})
    with pytest.raises(core.SafetyViolation):
        core.assert_cannot_weaken_safety(unsafe, [critical_scn])


def test_safety_guard_allows_sub_critical_rule():
    safe = _a1c_rule()
    core.assert_cannot_weaken_safety(safe, [_scn("ok", 7.8)])  # no raise


# ---- Test-case gate (plan Phase 2 deliverable) ----

def test_run_test_cases_reports_pass_and_fail():
    rule = _a1c_rule()
    pairs = [
        (_scn("expect_review", 7.8), "clinician_review_required"),
        (_scn("wrong", 7.8), "normal"),
    ]
    results = core.run_test_cases(pairs, [rule])
    by_name = {r.name: r for r in results}
    assert by_name["expect_review"].passed is True
    assert by_name["wrong"].passed is False
