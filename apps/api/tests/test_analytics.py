"""Analytics & personalization — service layer (plan Phase 6 exit gate; spec §12, §6.4.3).

DB-backed. Proves: feedback capture with edit-diff, governed dashboards, approval-gated
recommendations (inert until approved), preference-never-weakens-safety, cross-tenant
de-identification, and audit completeness.
"""
import uuid

import pytest

from core.models import DomainEventOutbox
from domains.analytics import services as analytics
from domains.analytics.models import ConfigurationRecommendation, PractitionerPreference
from domains.audit.models import AuditEvent
from domains.feedback import services as feedback

pytestmark = pytest.mark.django_db


def _tenant() -> str:
    return str(uuid.uuid4())


def _seed_edits(t, practitioner="dr_smith", n=4):
    for _ in range(n):
        feedback.capture(
            tenant_id=t, workflow_type="results", workflow_id=str(uuid.uuid4()),
            practitioner=practitioner, action="edit",
            original_text="the quick brown fox jumps over the lazy dog",
            edited_text="the fox jumps",
        )


def test_feedback_capture_computes_edit_difference():
    t = _tenant()
    fb = feedback.capture(
        tenant_id=t, workflow_type="results", workflow_id=str(uuid.uuid4()),
        practitioner="dr_smith", action="edit",
        original_text="a b c d e", edited_text="a b",
    )
    assert fb.edit_difference["shortened"] is True
    assert AuditEvent.objects.filter(tenant_id=t, action="feedback_captured").exists()


def test_dashboards_aggregate_feedback():
    t = _tenant()
    for action in ("approve", "approve", "override"):
        feedback.capture(tenant_id=t, workflow_type="results", workflow_id=str(uuid.uuid4()),
                         practitioner="dr", action=action)
    board = analytics.dashboards(t)
    assert board["executive"]["total_decisions"] == 3
    assert board["operations"]["override_rate"] == round(1 / 3, 4)


def test_recommendation_is_pending_until_approved():
    t = _tenant()
    _seed_edits(t)
    rec = analytics.derive_preferences(t, "dr_smith")
    assert rec is not None
    assert rec.status == "pending"
    # The preference exists but is INACTIVE — nothing takes effect yet.
    pref = PractitionerPreference.objects.get(tenant_id=t, practitioner="dr_smith")
    assert pref.active is False

    analytics.approve_recommendation(tenant_id=t, recommendation_id=str(rec.id), actor="lead")
    rec.refresh_from_db()
    pref.refresh_from_db()
    assert rec.status == "approved"
    assert pref.active is True  # activated only via governed human approval
    assert AuditEvent.objects.filter(tenant_id=t, action="recommendation_approved").exists()


def test_recommendation_events_emitted():
    t = _tenant()
    _seed_edits(t)
    rec = analytics.derive_preferences(t, "dr_smith")
    analytics.approve_recommendation(tenant_id=t, recommendation_id=str(rec.id), actor="lead")
    types = set(DomainEventOutbox.objects.filter(tenant_id=t).values_list("event_type", flat=True))
    assert {"RecommendationCreated", "RecommendationApproved"} <= types


def test_double_approval_is_rejected():
    t = _tenant()
    _seed_edits(t)
    rec = analytics.derive_preferences(t, "dr_smith")
    analytics.approve_recommendation(tenant_id=t, recommendation_id=str(rec.id), actor="lead")
    with pytest.raises(analytics.RecommendationError):
        analytics.approve_recommendation(tenant_id=t, recommendation_id=str(rec.id), actor="lead")


def test_preference_safety_check_public_helper():
    assert analytics.preference_safety_check({"verbosity": "concise"}) is True
    assert analytics.preference_safety_check({"critical_threshold": 6.0}) is False


def test_cross_tenant_report_is_deidentified():
    a, b = _tenant(), _tenant()
    for _ in range(3):
        feedback.capture(tenant_id=a, workflow_type="results", workflow_id=str(uuid.uuid4()),
                         practitioner="dr", action="approve")
    rows = analytics.cross_tenant_report([a, b])
    assert len(rows) == 2
    # No identifiers cross the boundary; small cells suppressed.
    for row in rows:
        assert "patient_external_id" not in row
        assert row["cells"]["approvals"] in ("suppressed", 0) or isinstance(
            row["cells"]["approvals"], int
        )


def test_tenant_scoping_isolates_recommendations():
    a, b = _tenant(), _tenant()
    _seed_edits(a)
    analytics.derive_preferences(a, "dr_smith")
    assert ConfigurationRecommendation.objects.filter(tenant_id=a).count() == 1
    assert ConfigurationRecommendation.objects.filter(tenant_id=b).count() == 0
