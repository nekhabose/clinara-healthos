"""Analytics & governed personalization service interface (spec §7.4, plan Phase 6).

Turns captured feedback into dashboards, derives *approval-gated* preference/config
recommendations, and enforces the two non-negotiables:

  * **Approval before effect** — recommendations are created ``pending`` and take effect only
    when a human approves them; approval routes through the governed pipeline (spec §6.4.3).
  * **Never weaken safety** — a derived preference is validated against the safety-protected
    field set (``core.assert_preference_safe``); a preference that touches a safety field is
    impossible to store.

Cross-tenant analysis is de-identified and small cells suppressed (spec §12.5) before any
data leaves a tenant boundary.
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
from domains.feedback.models import ClinicianFeedback

from . import core
from .core import EditDifference, PreferenceSafetyViolation
from .models import (
    AnalyticsSnapshot,
    ConfigurationRecommendation,
    PractitionerPreference,
    RecommendationStatus,
)


def _bind(tenant_id: str) -> None:
    current_tenant_id.set(str(tenant_id))
    _correlation_id.set(str(uuid.uuid4()))
    set_db_tenant(str(tenant_id))


def dashboards(tenant_id: str) -> dict[str, Any]:
    """Executive / Clinical / Operations dashboards (spec §12)."""
    _bind(tenant_id)
    actions = list(
        ClinicianFeedback.objects.filter(tenant_id=tenant_id).values_list("action", flat=True)
    )
    metrics = core.aggregate_feedback(actions).as_dict()
    by_type: dict[str, dict] = {}
    for wtype in ("results", "refill", "message", "coding"):
        t_actions = list(
            ClinicianFeedback.objects.filter(tenant_id=tenant_id, workflow_type=wtype)
            .values_list("action", flat=True)
        )
        by_type[wtype] = core.aggregate_feedback(t_actions).as_dict()
    board = {
        "executive": {"agreement_rate": metrics["agreement_rate"],
                      "total_decisions": metrics["total"]},
        "clinical": {"by_workflow_type": by_type, "overall": metrics},
        "operations": {"override_rate": metrics["override_rate"],
                       "escalation_rate": metrics["escalation_rate"]},
    }
    for scope, data in board.items():
        AnalyticsSnapshot.objects.create(tenant_id=tenant_id, scope=scope, metrics=data)
    return board


def derive_preferences(tenant_id: str, practitioner: str, *, target: str = "results_template",
                       min_observations: int = 3) -> ConfigurationRecommendation | None:
    """Derive a low-risk preference from a clinician's edits → a *pending* recommendation.

    Returns None when there is not enough signal. The recommendation is inert (pending) and
    the preference is stored ``active=False`` — nothing takes effect without approval.
    """
    _bind(tenant_id)
    edits = [
        EditDifference(
            original_length=fb.edit_difference.get("original_length", 0),
            edited_length=fb.edit_difference.get("edited_length", 0),
            added_words=fb.edit_difference.get("added_words", []),
            removed_words=fb.edit_difference.get("removed_words", []),
        )
        for fb in ClinicianFeedback.objects.filter(
            tenant_id=tenant_id, practitioner=practitioner, action="edit"
        )
        if fb.edit_difference
    ]
    signal = core.derive_preferences(practitioner, edits, min_observations=min_observations)
    if signal is None:
        return None

    with transaction.atomic():
        PractitionerPreference.objects.update_or_create(
            tenant_id=tenant_id, practitioner=practitioner,
            defaults={"adjustments": signal.adjustments, "derived_from": signal.derived_from,
                      "active": False},  # inert until approved
        )
        rec = core.recommend_from_signal(signal, target=target)
        recommendation = ConfigurationRecommendation.objects.create(
            tenant_id=tenant_id, kind=rec.kind, target=rec.target, proposal=rec.proposal,
            rationale=rec.rationale, supporting_observations=rec.supporting_observations,
            status=RecommendationStatus.PENDING,
        )
        audit.record(actor="system", action="recommendation_created",
                     resource=f"recommendation:{recommendation.id}", reason=rec.kind,
                     after_state={"target": rec.target, "status": "pending"})
        publish_event(
            event_type=EventType.RECOMMENDATION_CREATED.value,
            idempotency_key=f"recommendation:{recommendation.id}",
            payload={"recommendation_id": str(recommendation.id), "kind": rec.kind},
        )
    return recommendation


class RecommendationError(RuntimeError):
    pass


def approve_recommendation(*, tenant_id: str, recommendation_id: str, actor: str
                           ) -> ConfigurationRecommendation:
    """Human approval — the ONLY path by which a recommendation can take effect (spec §6.4.3).

    Re-validates safety, activates the associated preference, and marks the recommendation
    approved. Actual rollout still flows through the Phase 2 deployment pipeline (the
    approval is recorded here; deployment is a separate governed step).
    """
    _bind(tenant_id)
    with transaction.atomic():
        rec = ConfigurationRecommendation.objects.select_for_update().get(
            id=recommendation_id, tenant_id=tenant_id
        )
        if rec.status != RecommendationStatus.PENDING:
            raise RecommendationError(f"recommendation is {rec.status}, not pending")
        # Defence in depth: a recommendation can never carry a safety-weakening change.
        adjustments = rec.proposal.get("adjustments", {})
        core.assert_preference_safe(adjustments)

        practitioner = rec.proposal.get("practitioner")
        if practitioner:
            PractitionerPreference.objects.filter(
                tenant_id=tenant_id, practitioner=practitioner
            ).update(active=True)
        rec.status = RecommendationStatus.APPROVED
        rec.approved_by = actor
        rec.save(update_fields=["status", "approved_by", "updated_at"])
        audit.record(actor=actor, action="recommendation_approved",
                     resource=f"recommendation:{rec.id}", reason="approved",
                     before_state={"status": "pending"}, after_state={"status": "approved"})
        publish_event(
            event_type=EventType.RECOMMENDATION_APPROVED.value,
            idempotency_key=f"recommendation:{rec.id}:approved",
            payload={"recommendation_id": str(rec.id), "approved_by": actor},
        )
    return rec


def reject_recommendation(*, tenant_id: str, recommendation_id: str, actor: str
                          ) -> ConfigurationRecommendation:
    _bind(tenant_id)
    with transaction.atomic():
        rec = ConfigurationRecommendation.objects.select_for_update().get(
            id=recommendation_id, tenant_id=tenant_id
        )
        rec.status = RecommendationStatus.REJECTED
        rec.approved_by = actor
        rec.save(update_fields=["status", "approved_by", "updated_at"])
        audit.record(actor=actor, action="recommendation_rejected",
                     resource=f"recommendation:{rec.id}", reason="rejected")
    return rec


def cross_tenant_report(tenant_ids: list[str]) -> list[dict[str, Any]]:
    """De-identified, small-cell-suppressed cross-tenant rollup (spec §12.5, §4.2).

    Every record is de-identified and cohort counts below the aggregation threshold are
    suppressed before anything crosses a tenant boundary.
    """
    rows: list[dict[str, Any]] = []
    for tid in tenant_ids:
        _bind(tid)
        actions = list(
            ClinicianFeedback.objects.filter(tenant_id=tid).values_list("action", flat=True)
        )
        metrics = core.aggregate_feedback(actions)
        cells = core.suppress_small_cells({
            "approvals": metrics.approvals, "edits": metrics.edits,
            "overrides": metrics.overrides, "escalations": metrics.escalations,
        })
        rows.append(core.deidentify({
            "tenant": "redacted", "agreement_rate": metrics.agreement_rate, "cells": cells,
        }))
    return rows


def preference_safety_check(adjustments: dict) -> bool:
    """Public helper: True if the adjustments are safety-safe (no protected field)."""
    try:
        core.assert_preference_safe(adjustments)
        return True
    except PreferenceSafetyViolation:
        return False


__all__ = [
    "dashboards", "derive_preferences", "approve_recommendation", "reject_recommendation",
    "cross_tenant_report", "preference_safety_check", "RecommendationError",
]
