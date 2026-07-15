"""Output validation & safety gate (plan Phase 1, workstream 7 — spec §6.9.5/§6.9.6).

Runs with PYTHONPATH=apps/api.
"""
from datetime import datetime, timezone

from clinara_clinical_models import ContextProvenance, ContextSnapshot, ResultDecision
from clinara_shared_types import AutomationStatus, Priority, ResultClassification

from domains.generation.core import Draft, draft, load_templates
from domains.safety.core import FALLBACK_PATIENT_MESSAGE, validate

NOW = datetime(2026, 7, 14, tzinfo=timezone.utc)
TEMPLATES = load_templates("clinical/templates/results.yaml")


def _snap(facts):
    return ContextSnapshot(
        tenant_id="t", patient_id="p", facts=facts,
        provenance=ContextProvenance(context_builder_version="test"), context_created_at=NOW,
    )


def _decision():
    return ResultDecision(
        classification=ResultClassification.CLINICIAN_REVIEW_REQUIRED, priority=Priority.ELEVATED,
        recommended_action="evaluate_current_plan",
        automation_status=AutomationStatus.REQUIRES_CLINICIAN_APPROVAL,
        patient_message_template="diabetes_a1c_above_target_v1",
        reason_codes=["A1C_ABOVE_CONFIGURED_TARGET"], clinical_facts_used=["lab.a1c"],
    )


FACTS = {"lab.marker": "hemoglobin_a1c", "lab.value": 7.8, "lab.unit": "%",
         "lab.prior_value": 7.1, "lab.ref_high": 5.7}


def test_valid_draft_passes():
    d = draft(_decision(), _snap(FACTS), TEMPLATES)
    result = validate(d, _decision(), _snap(FACTS))
    assert result.passed is True
    assert result.used_fallback is False
    assert "7.8 %" in result.final_patient_message
    assert result.route_to_human is True  # Phase 1: always human


def test_hallucinated_number_triggers_fallback():
    # A rewrite injects a number that is not a known fact -> numeric-consistency failure.
    bad = Draft(
        patient_message="Your A1c is 7.8 % and your risk score is 42. This is general information, not a diagnosis.",
        clinician_summary="A1c 7.8%.", template_key="diabetes_a1c_above_target_v1",
        template=TEMPLATES["diabetes_a1c_above_target_v1"],
    )
    result = validate(bad, _decision(), _snap(FACTS))
    assert result.passed is False
    assert any(f.startswith("numeric_consistency") for f in result.failures)
    assert result.final_patient_message == FALLBACK_PATIENT_MESSAGE


def test_missing_required_warning_triggers_fallback():
    bad = Draft(
        patient_message="Your A1c is 7.8 %.",  # warning removed
        clinician_summary="A1c 7.8%.", template_key="diabetes_a1c_above_target_v1",
        template=TEMPLATES["diabetes_a1c_above_target_v1"],
    )
    result = validate(bad, _decision(), _snap(FACTS))
    assert result.passed is False
    assert any(f.startswith("required_warning") for f in result.failures)


def test_prohibited_diagnosis_claim_triggers_fallback():
    bad = Draft(
        patient_message="This confirms you have diabetes. This is general information, not a diagnosis.",
        clinician_summary="A1c 7.8%.", template_key="diabetes_a1c_above_target_v1",
        template=TEMPLATES["diabetes_a1c_above_target_v1"],
    )
    result = validate(bad, _decision(), _snap(FACTS))
    assert result.passed is False
    assert any(f.startswith("prohibited_claim") for f in result.failures)


def test_phi_in_message_triggers_fallback():
    bad = Draft(
        patient_message="Your A1c is 7.8 %. Contact 123-45-6789. This is general information, not a diagnosis.",
        clinician_summary="A1c 7.8%.", template_key="diabetes_a1c_above_target_v1",
        template=TEMPLATES["diabetes_a1c_above_target_v1"],
    )
    result = validate(bad, _decision(), _snap(FACTS))
    assert result.passed is False
    assert any(f.startswith("phi_boundary") for f in result.failures)


def test_fallback_preserves_deterministic_decision():
    # Even on generation failure, the decision object is untouched (spec §6.9.6).
    decision = _decision()
    bad = Draft(patient_message="risk 42", clinician_summary="", template_key="x", template=None)
    result = validate(bad, decision, _snap(FACTS))
    assert result.passed is False
    assert decision.classification is ResultClassification.CLINICIAN_REVIEW_REQUIRED
