"""Pure deterministic refill engine (plan Phase 4, workstream 3-4).

Runs with PYTHONPATH=apps/api, Django-free. Exercises the ordered safety cascade — the
crux of Phase 4 — proving safety exclusions always precede convenience and that no branch
is LLM-influenced.
"""
from clinara_shared_types import RefillOutcome
from clinara_terminology import ControlledSchedule, MedicationClass, MedicationSpec, map_medication

from domains.refills.core import RefillContext, evaluate_refill

STATIN = map_medication("RXNORM", "617314")          # Atorvastatin, non-controlled
OXYCODONE = map_medication("RXNORM", "1049221")      # Schedule II controlled


def _ctx(med=STATIN, **kw):
    return RefillContext(medication=med, **kw)


def test_missing_identity_blocks_automation():
    d = evaluate_refill(_ctx(med=None))
    assert d.outcome == RefillOutcome.ESCALATE_MISSING_DATA
    assert d.automation_allowed is False
    assert "MEDICATION_IDENTITY_UNRESOLVED" in d.reason_codes


def test_allergy_escalates_deterministically():
    d = evaluate_refill(_ctx(allergies=("atorvastatin",)))
    assert d.outcome == RefillOutcome.ESCALATE_CONTRAINDICATION
    assert "ALLERGY_TO_MEDICATION" in d.reason_codes
    assert "patient.allergies" in d.clinical_factors_used


def test_contraindication_escalates():
    d = evaluate_refill(_ctx(contraindications=("active_liver_disease",)))
    assert d.outcome == RefillOutcome.ESCALATE_CONTRAINDICATION


def test_interaction_routes_to_prescriber():
    d = evaluate_refill(_ctx(interactions=("gemfibrozil",)))
    assert d.outcome == RefillOutcome.ROUTE_TO_PRESCRIBER
    assert "INTERACTION_WITH_ACTIVE_MEDICATION" in d.reason_codes


def test_controlled_substance_always_escalates_and_never_automates():
    # Even with an otherwise-clean context and a client allowlist, a CII never auto-approves.
    d = evaluate_refill(
        _ctx(med=OXYCODONE,
             client_auto_approve_classes=frozenset({MedicationClass.OPIOID}))
    )
    assert d.outcome == RefillOutcome.ESCALATE_CONTROLLED_SUBSTANCE
    assert d.controlled_substance is True
    assert d.automation_allowed is False


def test_dose_mismatch_routes_to_prescriber():
    d = evaluate_refill(_ctx(requested_dose="40 MG", prescribed_dose="10 MG"))
    assert d.outcome == RefillOutcome.ROUTE_TO_PRESCRIBER
    assert "DOSE_MISMATCH" in d.reason_codes


def test_discontinued_is_rejected():
    d = evaluate_refill(_ctx(discontinued=True))
    assert d.outcome == RefillOutcome.REJECT_DISCONTINUED


def test_too_early_is_rejected():
    d = evaluate_refill(_ctx(days_since_last_fill=10, days_supply=90))
    assert d.outcome == RefillOutcome.REJECT_TOO_EARLY


def test_monitoring_labs_overdue_requests_labs():
    d = evaluate_refill(_ctx(days_since_last_fill=80, days_supply=90,
                             monitoring_labs_overdue=True))
    assert d.outcome == RefillOutcome.REQUEST_LABS


def test_visit_overdue_requests_appointment():
    d = evaluate_refill(_ctx(days_since_last_fill=80, days_supply=90,
                             last_visit_days_ago=400, visit_required_within_days=365))
    assert d.outcome == RefillOutcome.REQUEST_APPOINTMENT


def test_low_risk_one_click_when_not_client_approved():
    d = evaluate_refill(_ctx(days_since_last_fill=80, days_supply=90))
    assert d.outcome == RefillOutcome.ONE_CLICK_PREPARED
    assert d.automation_allowed is False


def test_low_risk_auto_approve_only_when_client_opts_in():
    d = evaluate_refill(
        _ctx(days_since_last_fill=80, days_supply=90,
             client_auto_approve_classes=frozenset({MedicationClass.STATIN}))
    )
    assert d.outcome == RefillOutcome.AUTO_APPROVE
    assert d.automation_allowed is True


def test_high_risk_state_suppresses_auto_approve():
    # Pregnancy blocks streamlined handling even for a client-approved low-risk class.
    d = evaluate_refill(
        _ctx(days_since_last_fill=80, days_supply=90, pregnancy=True,
             client_auto_approve_classes=frozenset({MedicationClass.STATIN}))
    )
    assert d.outcome == RefillOutcome.ROUTE_TO_NURSE
    assert d.automation_allowed is False


def test_safety_precedes_convenience():
    # An allergy on an otherwise auto-approvable statin still escalates — safety first.
    d = evaluate_refill(
        _ctx(days_since_last_fill=80, days_supply=90, allergies=("statin",),
             client_auto_approve_classes=frozenset({MedicationClass.STATIN}))
    )
    assert d.outcome == RefillOutcome.ESCALATE_CONTRAINDICATION


def test_unknown_medication_spec_is_controlled_flag_false():
    # Sanity: a non-controlled spec reports is_controlled False.
    spec = MedicationSpec("999", "Test", MedicationClass.STATIN, ControlledSchedule.NONE)
    assert spec.is_controlled is False
