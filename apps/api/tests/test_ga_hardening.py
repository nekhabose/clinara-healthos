"""GA hardening — service layer (spec §11.4, §10.2, §12.4, §15, §10.1).

DB-backed. Proves the emergency controls, reliability, DR, and compliance services persist
state, audit every action, and emit the right domain events — the Django glue on top of the
pure cores exercised in tests/unit.
"""
import pytest
from clinara_shared_types import KillSwitchScope

from core.models import DomainEventOutbox
from domains.audit.models import AuditEvent
from domains.compliance import services as compliance
from domains.compliance.core import EvidenceInput
from domains.continuity import services as continuity
from domains.continuity.core import OutboxRow, RestoreSnapshot, WorkflowRow
from domains.identity import services as identity
from domains.identity.models import BreakGlassGrantRecord
from domains.killswitch import services as killswitch
from domains.killswitch.core import AutomationAttempt
from domains.reliability import services as reliability

pytestmark = pytest.mark.django_db


# ---- Kill switch (spec §11.4) ----

def test_engage_suppresses_then_release_restores():
    attempt = AutomationAttempt(tenant_id="t1", workflow="results")
    assert killswitch.automation_allowed(attempt) is True

    killswitch.engage(
        scope=KillSwitchScope.WORKFLOW.value, target="results",
        reason="model anomaly", engaged_by="oncall",
    )
    decision = killswitch.check(attempt)
    assert decision.suppressed is True
    assert decision.scope is KillSwitchScope.WORKFLOW
    assert AuditEvent.objects.filter(action="killswitch.engage").exists()
    assert DomainEventOutbox.objects.filter(event_type="KillSwitchEngaged").exists()

    released = killswitch.release(
        scope=KillSwitchScope.WORKFLOW.value, target="results", released_by="oncall"
    )
    assert released == 1
    assert killswitch.automation_allowed(attempt) is True
    assert DomainEventOutbox.objects.filter(event_type="KillSwitchReleased").exists()


def test_global_kill_switch_suppresses_unrelated_attempt():
    killswitch.engage(scope="global", reason="platform incident", engaged_by="oncall")
    assert killswitch.automation_allowed(AutomationAttempt(tenant_id="anything")) is False


def test_engage_is_idempotent():
    killswitch.engage(scope="tenant", target="t1", reason="r", engaged_by="a")
    killswitch.engage(scope="tenant", target="t1", reason="r", engaged_by="a")
    from domains.killswitch.models import KillSwitchRecord
    assert KillSwitchRecord.objects.filter(active=True, scope="tenant", target="t1").count() == 1


# ---- Break-glass (spec §10.2) ----

def test_break_glass_grant_is_audited_and_time_boxed():
    grant = identity.grant_break_glass(
        responder="sec@clinara", reason="SEV1 triage", ttl_seconds=900
    )
    assert grant.expires_at > grant.granted_at
    assert identity.break_glass_active(grant) is True
    assert AuditEvent.objects.filter(action="breakglass.grant").exists()
    assert DomainEventOutbox.objects.filter(event_type="BreakGlassGranted").exists()


def test_break_glass_without_reason_is_refused_and_recorded():
    with pytest.raises(ValueError):
        identity.grant_break_glass(responder="r", reason="", ttl_seconds=900)
    assert AuditEvent.objects.filter(action="breakglass.denied").exists()
    assert not BreakGlassGrantRecord.objects.exists()


def test_break_glass_revoke_deactivates():
    grant = identity.grant_break_glass(responder="r", reason="triage", ttl_seconds=900)
    identity.revoke_break_glass(grant_id=str(grant.id), revoked_by="admin")
    grant.refresh_from_db()
    assert identity.break_glass_active(grant) is False
    assert DomainEventOutbox.objects.filter(event_type="BreakGlassRevoked").exists()


# ---- SLO monitoring (spec §12.4) ----

def test_slo_breach_is_persisted_and_announced():
    observed = {
        "ingestion_availability": 0.998,  # breach
        "routine_within_2min": 0.995,
        "critical_within_30s": 0.995,
        "silent_message_loss": 0.0,
        "audit_recording_success": 0.9999,
        "approved_channel_delivery": 0.995,
        "decision_trace_availability": 1.0,
    }
    report = reliability.evaluate_and_record(observed, window_label="2026-Q3")
    assert report.all_met is False
    from domains.reliability.models import SLOBreachRecord
    assert SLOBreachRecord.objects.filter(slo_key="ingestion_availability").exists()
    assert DomainEventOutbox.objects.filter(event_type="SLOBreached").exists()


def test_provider_failover_skips_killed_provider():
    killswitch.engage(scope="model_provider", target="anthropic", reason="x", engaged_by="a")
    sel = reliability.choose_provider(["anthropic", "openai"], {"anthropic": True, "openai": True})
    assert sel.provider == "openai"


# ---- DR reconciliation (spec §15) ----

def test_dr_drill_clean_restore_passes():
    snap = RestoreSnapshot(
        outbox=(OutboxRow("k1", published=True),),
        workflows=(WorkflowRow("w1", terminal=True),),
        data_loss_seconds=60,
        downtime_seconds=1800,
    )
    drill = continuity.run_drill(snap, label="quarterly-2026Q3")
    assert drill.outcome == "passed"
    assert DomainEventOutbox.objects.filter(event_type="DisasterRecoveryReconciled").exists()


def test_dr_drill_stranded_workflow_fails():
    snap = RestoreSnapshot(workflows=(WorkflowRow("w2", terminal=False),))
    drill = continuity.run_drill(snap, label="drill")
    assert drill.outcome == "failed"
    assert drill.stranded_count == 1


# ---- Compliance attestation (spec §10.1) ----

def test_attestation_persists_digest_and_events():
    ev = EvidenceInput(
        mutating_actions=10, mutating_actions_audited=10,
        phi_accesses=5, phi_accesses_logged=5,
        completed_workflows=8, completed_workflows_with_trace=8,
    )
    record = compliance.generate_attestation(ev, window_label="2026-Q3")
    assert record.attested is True
    assert len(record.evidence_digest) == 64
    assert DomainEventOutbox.objects.filter(event_type="AttestationGenerated").exists()


def test_attestation_with_gap_is_not_attested():
    ev = EvidenceInput(
        mutating_actions=10, mutating_actions_audited=9,
        phi_accesses=5, phi_accesses_logged=5,
        completed_workflows=8, completed_workflows_with_trace=8,
    )
    record = compliance.generate_attestation(ev, window_label="2026-Q3")
    assert record.attested is False
    assert record.gaps
