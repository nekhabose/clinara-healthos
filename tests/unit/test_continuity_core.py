"""DR reconciliation core (GA hardening — spec §15).

Django-free; runs with PYTHONPATH=apps/api. Proves recovery targets are checked explicitly
and no committed work is lost or left stranded after a restore.
"""
from domains.continuity import core


def test_clean_restore_meets_targets():
    snap = core.RestoreSnapshot(
        outbox=(core.OutboxRow("k1", published=True),),
        workflows=(core.WorkflowRow("w1", terminal=True),),
        data_loss_seconds=60,
        downtime_seconds=1800,
    )
    plan = core.reconcile(snap)
    assert plan.clean is True
    assert plan.replay_keys == ()
    assert plan.stranded_workflows == ()


def test_unpublished_events_are_queued_for_replay():
    snap = core.RestoreSnapshot(
        outbox=(
            core.OutboxRow("k1", published=True),
            core.OutboxRow("k2", published=False),
        ),
    )
    plan = core.reconcile(snap)
    assert plan.replay_keys == ("k2",)
    # Replay is expected work, not a failure — the drill is still clean.
    assert plan.clean is True


def test_stranded_workflow_fails_the_drill():
    snap = core.RestoreSnapshot(
        workflows=(
            core.WorkflowRow("w1", terminal=True),
            core.WorkflowRow("w2", terminal=False),
        ),
    )
    plan = core.reconcile(snap)
    assert plan.stranded_workflows == ("w2",)
    assert plan.clean is False


def test_rpo_breach_when_data_loss_exceeds_15min():
    snap = core.RestoreSnapshot(data_loss_seconds=core.RPO_SECONDS + 1)
    plan = core.reconcile(snap)
    assert plan.rpo_met is False
    assert plan.clean is False
    assert any("RPO breached" in n for n in plan.notes)


def test_rpo_met_exactly_at_boundary():
    plan = core.reconcile(core.RestoreSnapshot(data_loss_seconds=core.RPO_SECONDS))
    assert plan.rpo_met is True


def test_rto_breach_when_downtime_exceeds_4h():
    snap = core.RestoreSnapshot(downtime_seconds=core.RTO_SECONDS + 1)
    plan = core.reconcile(snap)
    assert plan.rto_met is False
    assert plan.clean is False
    assert any("RTO breached" in n for n in plan.notes)


def test_targets_match_spec():
    assert core.RPO_SECONDS == 15 * 60
    assert core.RTO_SECONDS == 4 * 60 * 60
