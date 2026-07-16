"""Patient Message Intelligence service interface (spec §7.4, plan Phase 5).

Wires the pure triage core (``messages.core``) to persistence, audit, and the outbox. The
governed order is fixed and cannot be reconfigured:

    store verbatim → detect language → **deterministic red-flag scan** → classify (LLM role)
      → deterministic urgency (red-flag floor ∨ category) → identity/contamination guard
      → route → (auto-draft only for approved non-clinical categories)

Emergencies escalate on the red-flag scan *regardless of model output*; high-risk categories
are never fully auto-resolved; cross-patient contamination is blocked before chart reasoning.
"""
from __future__ import annotations

import uuid
from typing import Any

from clinara_shared_types import EventType
from django.db import transaction

from clinara.middleware.phi_safe_logging import correlation_id as _correlation_id
from clinara.middleware.tenant import current_tenant_id, set_db_tenant
from core.outbox import publish_event
from domains.audit import services as audit

from . import core
from .core import Classifier, RuleBasedClassifier
from .models import (
    MessageClassificationRecord,
    MessageReview,
    MessageReviewAction,
    MessageStatus,
    PatientMessage,
)

# Approved, non-diagnostic auto-responses for low-risk non-clinical categories only.
_APPROVED_RESPONSES = {
    core.MessageCategory.APPOINTMENT: (
        "Thanks for your message. Our scheduling team will follow up to help with your "
        "appointment. This is general information, not medical advice."
    ),
    core.MessageCategory.BILLING: (
        "Thanks for your message. Our billing team will follow up about your account. "
        "This is general information, not medical advice."
    ),
    core.MessageCategory.ADMINISTRATIVE: (
        "Thanks for your message. Our administrative team will follow up shortly. "
        "This is general information, not medical advice."
    ),
}


def _bind(tenant_id: str, correlation: str) -> None:
    current_tenant_id.set(str(tenant_id))
    _correlation_id.set(correlation)
    set_db_tenant(str(tenant_id))


def process_message(*, tenant_id: str, payload: dict[str, Any],
                    classifier: Classifier | None = None,
                    context_patient_id: str | None = None) -> PatientMessage:
    """Triage one inbound patient message end to end (spec §6.2). Deterministic floor first."""
    classifier = classifier or RuleBasedClassifier()
    correlation = payload.get("idempotency_key") or str(uuid.uuid4())
    _bind(tenant_id, correlation)
    patient = str(payload["patient_external_id"])
    text = str(payload["text"])

    # Cross-patient contamination guard BEFORE any chart-based reasoning (spec §6.2.6).
    if context_patient_id is not None:
        core.validate_identity(message_patient_id=patient, context_patient_id=context_patient_id)

    language = core.detect_language(text)
    red_flags = core.detect_red_flags(text)                 # independent of the model
    classification = classifier.classify(text, language=language)
    urgency = core.assign_urgency(red_flags, classification)
    routing = core.route(urgency)

    draft = ""
    if routing.auto_resolvable:
        draft = _APPROVED_RESPONSES.get(classification.category, "")

    status = MessageStatus.ESCALATED if routing.escalated else (
        MessageStatus.ROUTED if not routing.auto_resolvable else MessageStatus.TRIAGED
    )

    with transaction.atomic():
        message = PatientMessage.objects.create(
            tenant_id=tenant_id, correlation_id=correlation, patient_external_id=patient,
            channel=payload.get("channel", "patient_portal"), original_text=text,
            language=language, category=classification.category.value,
            urgency=urgency.urgency.value, red_flags=urgency.red_flags,
            reason_codes=urgency.reason_codes, destination=routing.destination.value,
            auto_resolvable=routing.auto_resolvable, draft_response=draft, status=status,
        )
        MessageClassificationRecord.objects.create(
            tenant_id=tenant_id, message=message, category=classification.category.value,
            confidence=classification.confidence, urgency=urgency.urgency.value,
            red_flags=urgency.red_flags, symptoms=classification.symptoms,
            medications=classification.medications, summary=classification.summary,
        )
        audit.record(
            actor="system", action="message_triaged", resource=f"message:{message.id}",
            reason=urgency.urgency.value,
            after_state={"category": classification.category.value,
                         "urgency": urgency.urgency.value,
                         "red_flags": urgency.red_flags,
                         "destination": routing.destination.value},
        )
        publish_event(
            event_type=EventType.MESSAGE_CLASSIFIED.value,
            idempotency_key=f"{correlation}:classified",
            payload={"message_id": str(message.id), "urgency": urgency.urgency.value,
                     "red_flags": urgency.red_flags},
        )
        publish_event(
            event_type=EventType.MESSAGE_ROUTED.value,
            idempotency_key=f"{correlation}:routed",
            payload={"message_id": str(message.id), "destination": routing.destination.value,
                     "escalated": routing.escalated},
        )
    return message


# ---- Human actions (spec §6.2) ----

def _act(message_id: str, tenant_id: str, actor: str, action: str, new_status: str,
         response_text: str = "", reason: str = "") -> PatientMessage:
    _bind(tenant_id, str(uuid.uuid4()))
    with transaction.atomic():
        message = PatientMessage.objects.get(id=message_id, tenant_id=tenant_id)
        before = message.status
        MessageReview.objects.create(
            tenant_id=tenant_id, message=message, action=action, actor=actor,
            response_text=response_text, reason=reason,
        )
        message.status = new_status
        message.save(update_fields=["status", "updated_at"])
        audit.record(actor=actor, action="message_action", resource=f"message:{message.id}",
                     reason=reason or action,
                     before_state={"status": before}, after_state={"status": new_status})
    return message


def respond(message_id: str, *, tenant_id: str, actor: str, response_text: str) -> PatientMessage:
    return _act(message_id, tenant_id, actor, MessageReviewAction.RESPOND,
                MessageStatus.RESOLVED, response_text=response_text)


def escalate(message_id: str, *, tenant_id: str, actor: str, reason: str) -> PatientMessage:
    return _act(message_id, tenant_id, actor, MessageReviewAction.ESCALATE,
                MessageStatus.ESCALATED, reason=reason)


def route_to(message_id: str, *, tenant_id: str, actor: str, reason: str = "") -> PatientMessage:
    return _act(message_id, tenant_id, actor, MessageReviewAction.ROUTE,
                MessageStatus.ROUTED, reason=reason)


def resolve(message_id: str, *, tenant_id: str, actor: str) -> PatientMessage:
    return _act(message_id, tenant_id, actor, MessageReviewAction.RESOLVE, MessageStatus.RESOLVED)


__all__ = ["process_message", "respond", "escalate", "route_to", "resolve"]
