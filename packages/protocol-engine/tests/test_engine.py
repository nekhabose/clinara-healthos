"""Deterministic protocol engine (plan Phase 1, workstream 5).

These tests construct context snapshots directly (no Django, no I/O) so the engine's
safety ordering is pinned precisely. The headline guarantee — a rule can NEVER weaken a
critical threshold — is asserted explicitly.
"""
from datetime import datetime, timezone

from clinara_clinical_models import ContextProvenance, ContextSnapshot
from clinara_protocol_engine import Rule, evaluate
from clinara_shared_types import AutomationStatus, Priority, ResultClassification
from clinara_terminology import CanonicalMarker

NOW = datetime(2026, 7, 14, tzinfo=timezone.utc)


def snap(facts, *, conflicting=None):
    return ContextSnapshot(
        tenant_id="t", patient_id="p", facts=facts,
        provenance=ContextProvenance(
            conflicting_facts=conflicting or [], context_builder_version="test"
        ),
        context_created_at=NOW,
    )


def a1c_rule(**over):
    base = {
        "id": "a1c", "version": 1, "marker": "hemoglobin_a1c",
        "when": {"all": [
            {"fact": "patient.has_diabetes", "operator": "equals", "value": True},
            {"fact": "lab.a1c", "operator": "greater_than_or_equal", "value": 7.0},
        ]},
        "then": {"classification": "clinician_review_required",
                 "recommended_action": "evaluate_current_plan",
                 "patient_template": "t", "reason_codes": ["A1C_ABOVE_TARGET"]},
    }
    base.update(over)
    return Rule.model_validate(base)


def test_matching_rule_produces_structured_output():
    s = snap({"lab.supported": True, "lab.a1c": 8.0, "patient.has_diabetes": True})
    ev = evaluate(s, marker=CanonicalMarker.HEMOGLOBIN_A1C, rules=[a1c_rule()])
    d = ev.decision
    assert d.classification is ResultClassification.CLINICIAN_REVIEW_REQUIRED
    assert d.recommended_action == "evaluate_current_plan"
    assert "A1C_ABOVE_TARGET" in d.reason_codes
    assert "lab.a1c" in d.clinical_facts_used
    assert ev.trace.matched_rule_id == "a1c"


def test_rule_cannot_weaken_a_critical_value():
    # A malicious/erroneous rule tries to call a critical potassium "normal".
    weakener = Rule.model_validate({
        "id": "downgrade", "version": 99, "marker": "potassium",
        "when": {"all": [{"fact": "lab.potassium", "operator": "greater_than", "value": 0}]},
        "then": {"classification": "normal", "recommended_action": "none"},
    })
    s = snap({"lab.supported": True, "lab.potassium": 7.0})
    ev = evaluate(s, marker=CanonicalMarker.POTASSIUM, rules=[weakener])
    # The engine escalates regardless of the rule — criticals are evaluated first.
    assert ev.decision.classification is ResultClassification.CRITICAL_ESCALATION
    assert ev.decision.priority is Priority.CRITICAL
    assert ev.trace.critical_triggered is True


def test_missing_value_suppresses_automation():
    s = snap({"lab.supported": True})  # no lab.a1c
    ev = evaluate(s, marker=CanonicalMarker.HEMOGLOBIN_A1C, rules=[a1c_rule()])
    assert ev.decision.classification is ResultClassification.INSUFFICIENT_DATA
    assert ev.decision.automation_status is AutomationStatus.SUPPRESSED_MISSING_CONTEXT


def test_unsupported_unit_blocks():
    s = snap({"lab.supported": False})
    ev = evaluate(s, marker=CanonicalMarker.GLUCOSE, rules=[])
    assert ev.decision.classification is ResultClassification.UNSUPPORTED
    assert ev.decision.automation_status is AutomationStatus.BLOCKED_UNSUPPORTED


def test_conflicting_facts_require_manual_review():
    s = snap({"lab.supported": True, "lab.potassium": 4.2}, conflicting=["specimen_mismatch"])
    ev = evaluate(s, marker=CanonicalMarker.POTASSIUM, rules=[])
    assert ev.decision.classification is ResultClassification.CONFLICTING_DATA


def test_protected_cohort_excludes_general_rule():
    s = snap({"lab.supported": True, "lab.a1c": 8.0, "patient.has_diabetes": True,
              "patient.pregnancy": True, "lab.ref_high": 5.7})
    rule = a1c_rule(safety={"excluded_when": ["patient.pregnancy"]})
    ev = evaluate(s, marker=CanonicalMarker.HEMOGLOBIN_A1C, rules=[rule])
    # Rule excluded -> falls through to safe reference-range default, not the rule outcome.
    assert ev.decision.classification is ResultClassification.CLINICIAN_REVIEW_REQUIRED
    assert ev.trace.matched_rule_id is None


def test_no_rule_within_range_is_normal():
    s = snap({"lab.supported": True, "lab.potassium": 4.2,
              "lab.ref_low": 3.5, "lab.ref_high": 5.1})
    ev = evaluate(s, marker=CanonicalMarker.POTASSIUM, rules=[])
    assert ev.decision.classification is ResultClassification.NORMAL


def test_evaluation_is_deterministic():
    s = snap({"lab.supported": True, "lab.a1c": 8.0, "patient.has_diabetes": True})
    a = evaluate(s, marker=CanonicalMarker.HEMOGLOBIN_A1C, rules=[a1c_rule()])
    b = evaluate(s, marker=CanonicalMarker.HEMOGLOBIN_A1C, rules=[a1c_rule()])
    assert a.decision.model_dump() == b.decision.model_dump()
