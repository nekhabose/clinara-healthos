"""Phase 11 — Data Lifecycle & Compliance Hardening (closes G7).

Two layers: the pure retention/purge logic (no DB) and the governed service layer (per-tenant
policy, scheduled minimization, BAA-termination hard-purge, certificate of destruction). The
through-line is ``gaps.md §1`` and the Phase 11 exit gate: PHI past the window is purged on
schedule, the purge is deterministic + tenant-scoped, the audit trail is preserved, and a
termination purge is complete and certified.
"""
import uuid
from datetime import UTC, datetime, timedelta

import pytest

from domains.retention import catalog, core, services

# --------------------------------------------------------------------------------------
# Pure logic — no DB
# --------------------------------------------------------------------------------------


def test_resolve_windows_overlays_overrides_on_defaults():
    windows = core.resolve_windows({"raw_inbound": 30})
    assert windows["raw_inbound"] == 30                      # override applied
    assert windows["observations"] == catalog.DEFAULT_WINDOWS["observations"]  # default kept
    # Unknown keys are ignored by the resolver (the service rejects them at write time).
    assert "bogus" not in core.resolve_windows({"bogus": 5})


def test_validate_window_bounds_and_unknown_category():
    core.validate_window("raw_inbound", 90)  # ok
    with pytest.raises(core.WindowRejected):
        core.validate_window("raw_inbound", 0)                       # below MIN
    with pytest.raises(core.WindowRejected):
        core.validate_window("raw_inbound", catalog.MAX_RETENTION_DAYS + 1)  # above MAX
    with pytest.raises(core.WindowRejected):
        core.validate_window("not_a_category", 90)                    # unknown
    with pytest.raises(core.WindowRejected):
        core.validate_window("raw_inbound", True)                     # bool is not a day count


def test_cutoff_and_expiry_are_deterministic_at_the_boundary():
    now = datetime(2026, 7, 15, tzinfo=UTC)
    cutoff = core.cutoff_for(now, 90)
    assert cutoff == now - timedelta(days=90)
    assert core.is_expired(cutoff - timedelta(seconds=1), cutoff) is True
    assert core.is_expired(cutoff, cutoff) is False  # boundary row is KEPT (strictly older)


def test_certificate_hash_is_deterministic_and_content_bound():
    now = "2026-07-15T00:00:00+00:00"
    lines = (core.PurgeLine("raw_inbound", 3, "2026-04-16T00:00:00+00:00"),
             core.PurgeLine("observations", 2, "2025-07-15T00:00:00+00:00"))
    a = core.build_certificate(tenant_id="t", mode="scheduled", lines=lines,
                               audit_events_retained=5, issued_at_iso=now)
    b = core.build_certificate(tenant_id="t", mode="scheduled", lines=tuple(reversed(lines)),
                               audit_events_retained=5, issued_at_iso=now)
    assert a.content_hash == b.content_hash          # order-independent (lines sorted)
    assert a.total_purged == 5                        # derived, never trusted from caller
    # Any change to what was destroyed changes the digest.
    changed = (core.PurgeLine("raw_inbound", 4, "2026-04-16T00:00:00+00:00"),)
    c = core.build_certificate(tenant_id="t", mode="scheduled", lines=changed,
                               audit_events_retained=5, issued_at_iso=now)
    assert c.content_hash != a.content_hash


# --------------------------------------------------------------------------------------
# Governed service layer — DB
# --------------------------------------------------------------------------------------

pytestmark = pytest.mark.django_db


def _tenant() -> str:
    return str(uuid.uuid4())


def _old(days: int) -> datetime:
    return datetime.now(UTC) - timedelta(days=days)


def _make_inbound(tenant: str, *, created_days_ago: int):
    """Create a raw InboundMessage and force its created_at (auto_now_add) to the past."""
    from domains.integrations.models import InboundMessage
    msg = InboundMessage.objects.create(
        tenant_id=tenant, source="fhir-sandbox", message_type="Observation",
        idempotency_key=f"idem-{uuid.uuid4()}", raw_payload={"phi": "x"},
    )
    InboundMessage.objects.filter(id=msg.id).update(created_at=_old(created_days_ago))
    return msg


def _make_message(tenant: str, *, created_days_ago: int):
    from domains.messages.models import MessageClassificationRecord, PatientMessage
    m = PatientMessage.objects.create(
        tenant_id=tenant, correlation_id=str(uuid.uuid4()), patient_external_id="pat-1",
        original_text="my knee hurts",
    )
    # A cascading child to prove children go with the parent.
    MessageClassificationRecord.objects.create(
        tenant_id=tenant, message=m, category="symptom", urgency="routine",
    )
    PatientMessage.objects.filter(id=m.id).update(created_at=_old(created_days_ago))
    return m


# ---- Retention policy ----

def test_default_windows_are_minimal_necessary():
    t = _tenant()
    windows = services.effective_windows(t)
    assert windows["raw_inbound"] == 90       # tight window for raw inbound PHI
    assert windows["patient_messages"] == 90
    assert windows["observations"] == 365


def test_set_retention_window_validates_and_versions():
    from domains.audit.models import AuditEvent

    t = _tenant()
    p1 = services.set_retention_window(tenant_id=t, category="raw_inbound", days=30, actor="admin")
    assert services.effective_windows(t)["raw_inbound"] == 30
    assert p1.version == 1
    p2 = services.set_retention_window(tenant_id=t, category="observations", days=180,
                                       actor="admin")
    assert p2.version == 2  # same policy row, bumped
    assert AuditEvent.objects.filter(tenant_id=t, action="retention_policy_updated").count() == 2

    with pytest.raises(services.WindowRejected):
        services.set_retention_window(tenant_id=t, category="raw_inbound", days=0, actor="admin")
    with pytest.raises(services.WindowRejected):
        services.set_retention_window(tenant_id=t, category="nope", days=30, actor="admin")


# ---- Scheduled purge ----

def test_scheduled_purge_removes_expired_keeps_fresh():
    t = _tenant()
    old = _make_inbound(t, created_days_ago=120)   # past the 90-day window
    fresh = _make_inbound(t, created_days_ago=10)  # inside the window
    run = services.run_scheduled_purge(tenant_id=t)

    from domains.integrations.models import InboundMessage
    remaining = set(InboundMessage.objects.filter(tenant_id=t).values_list("id", flat=True))
    assert old.id not in remaining
    assert fresh.id in remaining
    assert run.purged_counts["raw_inbound"] == 1
    assert run.total_purged == 1


def test_scheduled_purge_cascades_children_and_is_audited_and_evented():
    from core.models import DomainEventOutbox
    from domains.audit.models import AuditEvent
    from domains.messages.models import MessageClassificationRecord, PatientMessage

    t = _tenant()
    _make_message(t, created_days_ago=200)
    assert MessageClassificationRecord.objects.filter(tenant_id=t).count() == 1

    run = services.run_scheduled_purge(tenant_id=t)
    assert PatientMessage.objects.filter(tenant_id=t).count() == 0
    assert MessageClassificationRecord.objects.filter(tenant_id=t).count() == 0  # cascaded
    assert run.purged_counts["patient_messages"] == 1

    assert AuditEvent.objects.filter(tenant_id=t, action="data_purge").exists()
    assert DomainEventOutbox.objects.filter(tenant_id=t, event_type="DataPurged").exists()


def test_scheduled_purge_is_idempotent():
    t = _tenant()
    _make_inbound(t, created_days_ago=120)
    first = services.run_scheduled_purge(tenant_id=t)
    second = services.run_scheduled_purge(tenant_id=t)
    assert first.total_purged == 1
    assert second.total_purged == 0  # nothing new to purge on the second pass


def test_dry_run_reports_counts_without_deleting():
    from domains.integrations.models import InboundMessage

    t = _tenant()
    _make_inbound(t, created_days_ago=120)
    run = services.plan_scheduled_purge(tenant_id=t)
    assert run.dry_run is True
    assert run.total_purged == 1
    # Nothing was actually deleted; no certificate issued for a dry run.
    assert InboundMessage.objects.filter(tenant_id=t).count() == 1
    assert services.latest_certificate(tenant_id=t) is None


def test_shorter_window_purges_more():
    t = _tenant()
    _make_inbound(t, created_days_ago=45)  # inside 90-day default, outside a 30-day window
    assert services.plan_scheduled_purge(tenant_id=t).total_purged == 0
    services.set_retention_window(tenant_id=t, category="raw_inbound", days=30, actor="admin")
    assert services.plan_scheduled_purge(tenant_id=t).total_purged == 1


def test_audit_trail_is_never_purged():
    from domains.audit.models import AuditEvent

    t = _tenant()
    _make_inbound(t, created_days_ago=200)
    services.set_retention_window(tenant_id=t, category="raw_inbound", days=30, actor="admin")
    before = AuditEvent.objects.filter(tenant_id=t).count()
    services.run_scheduled_purge(tenant_id=t)
    after = AuditEvent.objects.filter(tenant_id=t).count()
    assert after >= before  # audit only ever grows; the purge appended, never removed


# ---- Tenant isolation ----

def test_purge_cannot_cross_tenant_boundaries():
    from domains.integrations.models import InboundMessage

    t_a, t_b = _tenant(), _tenant()
    _make_inbound(t_a, created_days_ago=200)
    b_msg = _make_inbound(t_b, created_days_ago=200)
    services.run_scheduled_purge(tenant_id=t_a)  # purge ONLY tenant A
    # Tenant B's expired row is untouched — a purge is scoped to its tenant.
    assert InboundMessage.objects.filter(tenant_id=t_b, id=b_msg.id).exists()


# ---- BAA termination ----

def test_terminate_purges_all_phi_certifies_and_preserves_audit():
    from domains.audit.models import AuditEvent
    from domains.clinical_data.models import PatientReference
    from domains.integrations.models import InboundMessage

    t = _tenant()
    _make_inbound(t, created_days_ago=1)   # FRESH — a scheduled purge would keep it
    PatientReference.objects.create(tenant_id=t, external_id="pat-1")  # non-windowed reference
    audit_before = AuditEvent.objects.filter(tenant_id=t).count()

    cert = services.terminate_tenant(tenant_id=t, actor="admin", reason="contract ended")

    # Everything is gone, regardless of age.
    assert InboundMessage.objects.filter(tenant_id=t).count() == 0
    assert PatientReference.objects.filter(tenant_id=t).count() == 0
    assert cert.total_purged >= 2
    assert cert.mode == "termination"
    assert len(cert.content_hash) == 64

    # The audit trail survived and the certificate proves how much was retained.
    assert AuditEvent.objects.filter(tenant_id=t).count() >= audit_before
    assert cert.audit_events_retained >= audit_before
    # The policy is now marked terminated.
    assert services.get_policy(t).terminated is True


def test_certificate_hash_matches_the_pure_core_recomputation():
    from domains.integrations.models import InboundMessage

    t = _tenant()
    _make_inbound(t, created_days_ago=1)
    cert = services.terminate_tenant(tenant_id=t, actor="admin")
    # Recompute the digest from the stored lines — an auditor's tamper check.
    lines = tuple(core.PurgeLine(line["category"], line["purged"], line["cutoff"])
                  for line in cert.lines)
    recomputed = core.build_certificate(
        tenant_id=t, mode="termination", lines=lines,
        audit_events_retained=cert.audit_events_retained,
        issued_at_iso=cert.purge_run.finished_at.isoformat(),
    )
    assert recomputed.content_hash == cert.content_hash
    assert InboundMessage.objects.filter(tenant_id=t).count() == 0


def test_purge_all_tenants_skips_terminated_and_sweeps_active():
    from domains.tenants.models import Organization

    org_a = Organization.objects.create(name="A", slug=f"a-{uuid.uuid4().hex[:8]}")
    org_b = Organization.objects.create(name="B", slug=f"b-{uuid.uuid4().hex[:8]}")
    _make_inbound(str(org_a.id), created_days_ago=200)
    _make_inbound(str(org_b.id), created_days_ago=200)
    # Terminate B — it should be skipped by the all-tenant sweep.
    services.terminate_tenant(tenant_id=str(org_b.id), actor="admin")

    total = services.purge_all_tenants()
    # A's expired inbound purged (1); B already terminated (0 additional).
    assert total == 1
