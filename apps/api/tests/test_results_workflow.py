"""End-to-end results workflow via the service layer (plan Phase 1 exit gate — spec §19).

DB-backed (SQLite by default). Proves ingest → canonical → context → decision → validated
communication → persisted reviewable workflow, plus audit, outbox events, idempotency, the
unknown-code queue, critical handling, and replay determinism.
"""
import uuid

import pytest

from core.models import DomainEventOutbox
from domains.audit.models import AuditEvent
from domains.clinical_data.models import Observation
from domains.integrations import services as integrations
from domains.operations.models import OperationsQueueItem
from domains.terminology.models import MappingProposal
from domains.workflows import services as workflows
from domains.workflows.models import GeneratedCommunication, WorkflowInstance

pytestmark = pytest.mark.django_db


def _tenant() -> str:
    return str(uuid.uuid4())


def _payload(code="4548-4", value=7.8, unit="%", facts=None,
             observed="2026-07-10T09:00:00+00:00", patient="P1"):
    return {
        "patient_external_id": patient, "code_system": "LOINC", "code": code,
        "value": value, "unit": unit, "observed_at": observed,
        "patient_facts": facts or {}, "specialty": "primary_care",
    }


def test_ingest_creates_reviewable_workflow():
    t = _tenant()
    _, workflow, created = integrations.ingest_and_process(
        tenant_id=t, payload=_payload(facts={"patient.has_diabetes": True})
    )
    assert created is True
    assert workflow.status == "pending_review"
    assert workflow.classification == "clinician_review_required"
    comm = GeneratedCommunication.objects.get(workflow=workflow)
    assert comm.validation_passed is True
    assert "not a diagnosis" in comm.patient_message
    assert Observation.objects.filter(tenant_id=t).count() == 1


def test_duplicate_delivery_is_idempotent():
    t = _tenant()
    p = _payload(facts={"patient.has_diabetes": True})
    integrations.ingest_and_process(tenant_id=t, payload=p)
    _, workflow2, created2 = integrations.ingest_and_process(tenant_id=t, payload=p)
    assert created2 is False
    assert workflow2 is None  # duplicate never reprocessed (spec §6.7.6)
    assert WorkflowInstance.objects.filter(tenant_id=t).count() == 1
    assert Observation.objects.filter(tenant_id=t).count() == 1


def test_unknown_code_parks_on_queue_and_creates_no_workflow():
    t = _tenant()
    _, workflow, _ = integrations.ingest_and_process(tenant_id=t, payload=_payload(code="9999-9"))
    assert workflow is None
    assert MappingProposal.objects.filter(tenant_id=t, code="9999-9").exists()
    assert OperationsQueueItem.objects.filter(tenant_id=t, kind="unmapped_code").exists()
    assert WorkflowInstance.objects.filter(tenant_id=t).count() == 0


def test_critical_value_escalates_with_no_patient_message():
    t = _tenant()
    _, workflow, _ = integrations.ingest_and_process(
        tenant_id=t, payload=_payload(code="2823-3", value=6.8, unit="mmol/L")
    )
    assert workflow.classification == "critical_escalation"
    assert workflow.priority == "critical"
    comm = GeneratedCommunication.objects.get(workflow=workflow)
    assert comm.patient_message == ""  # criticals never auto-draft a patient message


def test_unsupported_unit_blocks_and_queues():
    t = _tenant()
    _, workflow, _ = integrations.ingest_and_process(
        tenant_id=t, payload=_payload(code="2345-7", value=5.0, unit="g/L")
    )
    assert workflow.status == "blocked"
    assert workflow.classification == "unsupported"
    assert OperationsQueueItem.objects.filter(tenant_id=t, kind="unsupported_unit").exists()


def test_decision_is_audited_and_events_emitted():
    t = _tenant()
    _, workflow, _ = integrations.ingest_and_process(
        tenant_id=t, payload=_payload(facts={"patient.has_diabetes": True})
    )
    assert AuditEvent.objects.filter(
        tenant_id=t, action="workflow_decision", resource=f"workflow:{workflow.id}"
    ).exists()
    types = set(
        DomainEventOutbox.objects.filter(tenant_id=t).values_list("event_type", flat=True)
    )
    assert {"ObservationReceived", "ProtocolEvaluated", "DecisionCreated",
            "CommunicationValidated"} <= types


def test_prior_value_produces_trend():
    t = _tenant()
    integrations.ingest_and_process(
        tenant_id=t, payload=_payload(value=7.1, observed="2026-01-01T00:00:00+00:00",
                                      facts={"patient.has_diabetes": True})
    )
    _, workflow2, _ = integrations.ingest_and_process(
        tenant_id=t, payload=_payload(value=7.8, observed="2026-06-01T00:00:00+00:00",
                                      facts={"patient.has_diabetes": True})
    )
    from domains.context.models import ContextSnapshotRecord
    snap = ContextSnapshotRecord.objects.get(workflow_id=workflow2.id)
    assert snap.facts["lab.prior_value"] == 7.1
    assert snap.facts["lab.trend"] == "rising"


def test_replay_reproduces_decision():
    t = _tenant()
    _, workflow, _ = integrations.ingest_and_process(
        tenant_id=t, payload=_payload(facts={"patient.has_diabetes": True})
    )
    result = workflows.replay(str(workflow.id), tenant_id=t)
    assert result["matches"] is True


def test_clinician_approve_and_edit_are_audited():
    t = _tenant()
    _, workflow, _ = integrations.ingest_and_process(
        tenant_id=t, payload=_payload(facts={"patient.has_diabetes": True})
    )
    workflows.approve(str(workflow.id), tenant_id=t, actor="dr_smith")
    workflow.refresh_from_db()
    assert workflow.status == "approved"

    workflows.edit(str(workflow.id), tenant_id=t, actor="dr_smith",
                   edited_message="Adjusted wording.")
    workflow.refresh_from_db()
    assert workflow.status == "edited"
    assert workflow.reviews.filter(action="edit", edited_message="Adjusted wording.").exists()
    assert AuditEvent.objects.filter(tenant_id=t, action="clinician_action").count() >= 2
