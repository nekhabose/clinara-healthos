"""Patient message triage — service layer (plan Phase 5 exit gate; spec §6.2).

DB-backed. Proves: emergencies escalate on the deterministic red-flag scan regardless of the
model, high-risk categories are never auto-resolved, cross-patient contamination is blocked,
verbatim storage, audit, and events.
"""
import uuid

import pytest

from core.models import DomainEventOutbox
from domains.audit.models import AuditEvent
from domains.messages import core
from domains.messages import services as messages
from domains.messages.core import Classification, MessageCategory
from domains.messages.models import PatientMessage

pytestmark = pytest.mark.django_db


def _tenant() -> str:
    return str(uuid.uuid4())


def _payload(text, patient="P1", **over):
    p = {"patient_external_id": patient, "text": text, "channel": "patient_portal"}
    p.update(over)
    return p


class _MisclassifyingClassifier:
    """Simulates an LLM that wrongly calls an emergency 'administrative' with high confidence."""

    def classify(self, text, *, language):
        return Classification(category=MessageCategory.ADMINISTRATIVE, confidence=0.99)


def test_emergency_escalates_independent_of_model():
    t = _tenant()
    m = messages.process_message(
        tenant_id=t, payload=_payload("I have severe chest pain and can't breathe"),
        classifier=_MisclassifyingClassifier(),  # model says 'administrative'
    )
    # Deterministic red-flag floor overrides the model → emergency + escalated.
    assert m.urgency == "emergency"
    assert m.status == "escalated"
    assert m.destination == "emergency_escalation"
    assert m.red_flags  # recorded independent of the classifier


def test_verbatim_storage_and_audit():
    t = _tenant()
    text = "I need to reschedule my appointment please"
    m = messages.process_message(tenant_id=t, payload=_payload(text))
    assert m.original_text == text  # stored verbatim
    assert AuditEvent.objects.filter(tenant_id=t, action="message_triaged").exists()


def test_clinical_message_is_not_auto_resolved():
    t = _tenant()
    m = messages.process_message(tenant_id=t, payload=_payload("I have a fever and a rash"))
    assert m.auto_resolvable is False
    assert m.category == "clinical_symptom"


def test_administrative_message_gets_approved_draft():
    t = _tenant()
    m = messages.process_message(tenant_id=t, payload=_payload("Question about my bill"))
    assert m.auto_resolvable is True
    assert "not medical advice" in m.draft_response


def test_cross_patient_contamination_is_blocked():
    t = _tenant()
    with pytest.raises(core.ContaminationError):
        messages.process_message(
            tenant_id=t, payload=_payload("I have a headache", patient="P1"),
            context_patient_id="P2",  # chart assembled for a different patient
        )


def test_triage_emits_events():
    t = _tenant()
    messages.process_message(tenant_id=t, payload=_payload("chest pain"))
    types = set(DomainEventOutbox.objects.filter(tenant_id=t).values_list("event_type", flat=True))
    assert {"MessageClassified", "MessageRouted"} <= types


def test_clinician_respond_resolves_and_audits():
    t = _tenant()
    m = messages.process_message(tenant_id=t, payload=_payload("question about my medication dose"))
    messages.respond(str(m.id), tenant_id=t, actor="dr_lee", response_text="Take as prescribed.")
    m.refresh_from_db()
    assert m.status == "resolved"
    assert AuditEvent.objects.filter(tenant_id=t, action="message_action").exists()


def test_tenant_scoping_isolates_messages():
    a, b = _tenant(), _tenant()
    messages.process_message(tenant_id=a, payload=_payload("hello"))
    assert PatientMessage.objects.filter(tenant_id=a).count() == 1
    assert PatientMessage.objects.filter(tenant_id=b).count() == 0
