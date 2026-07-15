"""End-to-end pipeline + replay determinism (plan Phase 1 exit gate — spec §19).

Proves the §1.1 pipeline runs input→decision→draft→validated in one pass, and that
re-running the same input reproduces byte-identical decisions (replay).

Runs with PYTHONPATH=apps/api.
"""
from datetime import datetime, timezone

from clinara_protocol_engine import load_rules
from clinara_shared_types import AutomationStatus, ResultClassification

from domains.generation.core import load_templates
from domains.workflows.core import run_result_pipeline

RULES = load_rules("clinical/protocols")
TEMPLATES = load_templates("clinical/templates/results.yaml")
NOW = datetime(2026, 7, 14, tzinfo=timezone.utc)


def _run():
    return run_result_pipeline(
        tenant_id="t", patient_id="p", system="LOINC", code="4548-4", value=7.8, unit="%",
        observed_at=NOW, now=NOW, rules=RULES, templates=TEMPLATES,
        patient_facts={"patient.has_diabetes": True}, prior_value=7.1,
        specialty="primary_care", source_record_ids=["obs-1"],
    )


def test_full_pipeline_produces_validated_output():
    r = _run()
    assert r.status == "decided"
    assert r.evaluation.decision.classification is ResultClassification.CLINICIAN_REVIEW_REQUIRED
    assert r.evaluation.decision.automation_status is AutomationStatus.REQUIRES_CLINICIAN_APPROVAL
    assert r.validation.passed is True
    assert r.validation.final_patient_message is not None
    # No automated patient delivery without approval (Phase 1 exit gate).
    assert r.validation.route_to_human is True


def test_replay_is_deterministic():
    a, b = _run(), _run()
    assert a.evaluation.decision.model_dump() == b.evaluation.decision.model_dump()
    assert a.validation.final_patient_message == b.validation.final_patient_message


def test_critical_never_yields_patient_message():
    r = run_result_pipeline(
        tenant_id="t", patient_id="p", system="LOINC", code="2823-3", value=7.0, unit="mmol/L",
        observed_at=NOW, now=NOW, rules=RULES, templates=TEMPLATES,
    )
    assert r.evaluation.decision.classification is ResultClassification.CRITICAL_ESCALATION
    assert r.validation.final_patient_message is None  # critical goes to a clinician
