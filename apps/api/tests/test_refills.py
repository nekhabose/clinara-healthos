"""Refill workflow — service layer (plan Phase 4 exit gate; spec §6.3).

DB-backed. Proves the deterministic refill decision persists with the exact factors used,
safety exclusions are enforced, controlled substances always require a human, unknown
medications are queued (not guessed), and clinician actions are audited + emit events.
"""
import uuid

import pytest

from core.models import DomainEventOutbox
from domains.audit.models import AuditEvent
from domains.operations.models import OperationsQueueItem
from domains.refills import services as refills
from domains.refills.models import (
    AllergyIntolerance,
    ClientMonitoringPolicy,
    RefillEvaluationRecord,
    RefillWorkflow,
)

pytestmark = pytest.mark.django_db


def _tenant() -> str:
    return str(uuid.uuid4())


def _payload(code="617314", **over):
    p = {"patient_external_id": "P1", "code_system": "RXNORM", "code": code,
         "requested_dose": "10 MG", "days_since_last_fill": 80, "days_supply": 90}
    p.update(over)
    return p


def test_refill_decision_persists_exact_factors():
    t = _tenant()
    w = refills.process_refill_request(tenant_id=t, payload=_payload())
    ev = RefillEvaluationRecord.objects.get(workflow=w)
    assert ev.outcome == w.outcome
    assert ev.clinical_factors_used  # exact data used is recorded (spec §6.3.5)
    assert AuditEvent.objects.filter(tenant_id=t, action="refill_decision").exists()


def test_low_risk_auto_approve_when_client_policy_opts_in():
    t = _tenant()
    ClientMonitoringPolicy.objects.create(tenant_id=t, med_class="statin", auto_approve=True)
    w = refills.process_refill_request(tenant_id=t, payload=_payload())
    assert w.outcome == "auto_approve"
    assert w.automation_allowed is True
    assert w.status == "auto_approved"


def test_low_risk_without_policy_is_one_click_not_auto():
    t = _tenant()
    w = refills.process_refill_request(tenant_id=t, payload=_payload())
    assert w.outcome == "one_click_prepared"
    assert w.automation_allowed is False


def test_controlled_substance_always_escalates():
    t = _tenant()
    # Even if the client tried to auto-approve opioids, a CII escalates to a human.
    ClientMonitoringPolicy.objects.create(tenant_id=t, med_class="opioid", auto_approve=True)
    w = refills.process_refill_request(tenant_id=t, payload=_payload(code="1049221"))
    assert w.outcome == "escalate_controlled_substance"
    assert w.controlled_substance is True
    assert w.automation_allowed is False


def test_allergy_blocks_via_stored_facts():
    t = _tenant()
    AllergyIntolerance.objects.create(tenant_id=t, patient_external_id="P1",
                                      substance="atorvastatin")
    w = refills.process_refill_request(tenant_id=t, payload=_payload())
    assert w.outcome == "escalate_contraindication"


def test_dose_mismatch_uses_stored_prescribed_dose():
    t = _tenant()
    refills.upsert_medication_statement(
        tenant_id=t, patient_external_id="P1", rxnorm="617314",
        prescribed_dose="10 MG", days_supply=90, last_fill_days_ago=80,
    )
    w = refills.process_refill_request(tenant_id=t, payload=_payload(requested_dose="40 MG"))
    assert w.outcome == "route_to_prescriber"


def test_unknown_medication_escalates_and_queues():
    t = _tenant()
    w = refills.process_refill_request(tenant_id=t, payload=_payload(code="000000"))
    assert w.outcome == "escalate_missing_data"
    assert OperationsQueueItem.objects.filter(tenant_id=t, kind="unmapped_code").exists()


def test_clinician_actions_audited_and_emit_events():
    t = _tenant()
    w = refills.process_refill_request(tenant_id=t, payload=_payload())
    refills.approve(str(w.id), tenant_id=t, actor="nurse_jane")
    w.refresh_from_db()
    assert w.status == "approved"
    assert AuditEvent.objects.filter(tenant_id=t, action="refill_action").exists()
    types = set(DomainEventOutbox.objects.filter(tenant_id=t).values_list("event_type", flat=True))
    assert {"RefillEvaluated", "RefillDecided"} <= types


def test_tenant_scoping_isolates_refills():
    a, b = _tenant(), _tenant()
    refills.process_refill_request(tenant_id=a, payload=_payload())
    assert RefillWorkflow.objects.filter(tenant_id=a).count() == 1
    assert RefillWorkflow.objects.filter(tenant_id=b).count() == 0
