"""Feedback service interface (spec §7.4, plan Phase 6).

Captures clinician actions on generated outputs into structured feedback (with edit-diff
analysis) that personalization is later derived from. This domain only *records* — it never
changes behaviour. Every capture is audited and emits ``FeedbackCaptured``.
"""
from __future__ import annotations

import uuid

from clinara_shared_types import EventType
from django.db import transaction

from clinara.middleware.phi_safe_logging import correlation_id as _correlation_id
from clinara.middleware.tenant import current_tenant_id, set_db_tenant
from core.outbox import publish_event
from domains.analytics.core import edit_difference
from domains.audit import services as audit

from .models import ClinicianFeedback


def _bind(tenant_id: str) -> None:
    current_tenant_id.set(str(tenant_id))
    _correlation_id.set(str(uuid.uuid4()))
    set_db_tenant(str(tenant_id))


def capture(*, tenant_id: str, workflow_type: str, workflow_id: str, practitioner: str,
            action: str, original_text: str = "", edited_text: str = "",
            protocol_key: str = "", specialty: str = "", reason: str = "") -> ClinicianFeedback:
    """Record one clinician action. Computes the edit difference for ``edit`` actions."""
    _bind(tenant_id)
    diff = {}
    if action == "edit" and (original_text or edited_text):
        diff = edit_difference(original_text, edited_text).as_dict()
    with transaction.atomic():
        fb = ClinicianFeedback.objects.create(
            tenant_id=tenant_id, workflow_type=workflow_type, workflow_id=workflow_id,
            practitioner=practitioner, action=action, protocol_key=protocol_key,
            specialty=specialty, original_text=original_text, edited_text=edited_text,
            edit_difference=diff, reason=reason,
        )
        audit.record(actor=practitioner, action="feedback_captured",
                     resource=f"feedback:{fb.id}", reason=action,
                     after_state={"workflow_type": workflow_type, "action": action})
        publish_event(
            event_type=EventType.FEEDBACK_CAPTURED.value,
            idempotency_key=f"{workflow_id}:{action}:{fb.id}",
            payload={"workflow_type": workflow_type, "action": action,
                     "practitioner": practitioner},
        )
    return fb


def actions_for(tenant_id: str, *, workflow_type: str | None = None) -> list[str]:
    """The list of recorded actions (for aggregation), optionally filtered by workflow type."""
    _bind(tenant_id)
    qs = ClinicianFeedback.objects.filter(tenant_id=tenant_id)
    if workflow_type:
        qs = qs.filter(workflow_type=workflow_type)
    return list(qs.values_list("action", flat=True))


__all__ = ["capture", "actions_for"]
