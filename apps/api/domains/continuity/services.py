"""Continuity service interface (spec §15, §7.4).

Runs a DR reconciliation from a restore snapshot, persists the drill outcome, and publishes
``DisasterRecoveryReconciled``. The pure core decides *what* to reconcile and whether targets
were met; this layer records the drill and hands the replay/reconciliation work to the
existing outbox relay and durable saga runner.
"""
from __future__ import annotations

from clinara_shared_types import EventType
from django.db import transaction

from core.outbox import publish_event
from domains.audit import services as audit

from .core import RestoreSnapshot, reconcile
from .models import DisasterRecoveryDrill, DrillOutcome


@transaction.atomic
def run_drill(snapshot: RestoreSnapshot, *, label: str) -> DisasterRecoveryDrill:
    """Reconcile a restore, persist the outcome, and announce it. Fails loudly if not clean."""
    plan = reconcile(snapshot)
    drill = DisasterRecoveryDrill.objects.create(
        label=label,
        outcome=DrillOutcome.PASSED if plan.clean else DrillOutcome.FAILED,
        rpo_met=plan.rpo_met,
        rto_met=plan.rto_met,
        data_loss_seconds=plan.data_loss_seconds,
        downtime_seconds=plan.downtime_seconds,
        replay_count=len(plan.replay_keys),
        stranded_count=len(plan.stranded_workflows),
        notes=list(plan.notes),
    )
    audit.record(
        actor="system",
        action="dr.drill",
        resource=f"dr-drill:{drill.id}",
        reason=label,
        after_state={
            "outcome": drill.outcome,
            "rpo_met": plan.rpo_met,
            "rto_met": plan.rto_met,
        },
    )
    publish_event(
        event_type=EventType.DR_RECONCILED.value,
        idempotency_key=f"dr-drill-{drill.id}",
        payload={
            "label": label,
            "outcome": drill.outcome,
            "replay_count": drill.replay_count,
            "stranded_count": drill.stranded_count,
        },
    )
    return drill


__all__ = ["run_drill", "reconcile", "RestoreSnapshot"]
