"""Constrained generation (plan Phase 1, workstream 6 — spec §6.9.4).

Runs with PYTHONPATH=apps/api (the pure domain-core layer is Django-free).
"""
from datetime import datetime, timezone

from clinara_clinical_models import ContextProvenance, ContextSnapshot, ResultDecision
from clinara_shared_types import AutomationStatus, Priority, ResultClassification

from domains.generation.core import draft, load_templates

NOW = datetime(2026, 7, 14, tzinfo=timezone.utc)
TEMPLATES = load_templates("clinical/templates/results.yaml")


def _snapshot(facts):
    return ContextSnapshot(
        tenant_id="t", patient_id="p", facts=facts,
        provenance=ContextProvenance(context_builder_version="test"),
        context_created_at=NOW,
    )


def _decision(template):
    return ResultDecision(
        classification=ResultClassification.CLINICIAN_REVIEW_REQUIRED,
        priority=Priority.ELEVATED, recommended_action="evaluate_current_plan",
        automation_status=AutomationStatus.REQUIRES_CLINICIAN_APPROVAL,
        patient_message_template=template, reason_codes=["A1C_ABOVE_CONFIGURED_TARGET"],
        clinical_facts_used=["lab.a1c"],
    )


def test_default_renderer_uses_only_structured_facts():
    snap = _snapshot({"lab.marker": "hemoglobin_a1c", "lab.value": 7.8, "lab.unit": "%",
                      "lab.prior_value": 7.1, "lab.trend": "rising"})
    d = draft(_decision("diabetes_a1c_above_target_v1"), snap, TEMPLATES)
    assert "7.8 %" in d.patient_message
    assert "not a diagnosis" in d.patient_message  # required warning present
    assert d.template_key == "diabetes_a1c_above_target_v1"
    # No LLM involved: the platform still produces safe output (plan §1.1 invariant 1).


def test_no_template_yields_clinician_only_draft():
    snap = _snapshot({"lab.marker": "potassium", "lab.value": 6.8, "lab.unit": "mmol/L"})
    d = draft(_decision(None), snap, TEMPLATES)
    assert d.patient_message is None
    assert "Potassium" in d.clinician_summary


def test_injected_llm_only_rewrites_tone():
    snap = _snapshot({"lab.marker": "hemoglobin_a1c", "lab.value": 7.8, "lab.unit": "%"})

    class Shouty:
        def rewrite(self, text, instruction):
            return text.upper()

    d = draft(_decision("diabetes_a1c_above_target_v1"), snap, TEMPLATES, llm=Shouty())
    assert d.patient_message == d.patient_message.upper()  # rewrite applied; gate checks facts later
