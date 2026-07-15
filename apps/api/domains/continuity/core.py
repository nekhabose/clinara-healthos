"""Disaster-recovery reconciliation (GA hardening — spec §15).

After a restore-from-backup or point-in-time recovery, the platform must prove it lost no
committed work and left no workflow stranded. This module is the pure, Django-free
reconciliation core. Given a snapshot of what the restored database contains, it produces a
``ReconciliationPlan``: which domain events must be re-published (outbox rows that never
reached the bus), which workflows are stranded mid-flight and need operator attention, and
whether the achieved recovery point/time met the spec §15 targets.

Targets (spec §15): RTO 4h for core services, RPO 15 minutes for transactional data. These
are encoded as constants and checked explicitly so a drill that misses them fails loudly
rather than being reported as a success.

Why pure: the reconciliation decision must be replayable and testable without a live cluster.
The Django/ops layer feeds it the restored state and executes the plan (replay via the
existing outbox relay; workflow reconciliation via the durable saga runner).
"""
from __future__ import annotations

from dataclasses import dataclass, field

# Spec §15 recovery targets.
RTO_SECONDS = 4 * 60 * 60  # 4 hours, core services
RPO_SECONDS = 15 * 60  # 15 minutes, transactional data


@dataclass(frozen=True)
class OutboxRow:
    """A domain-event outbox row as found in the restored DB."""

    idempotency_key: str
    published: bool


@dataclass(frozen=True)
class WorkflowRow:
    """A workflow as found in the restored DB. ``terminal`` = reached a final state."""

    workflow_id: str
    terminal: bool


@dataclass(frozen=True)
class RestoreSnapshot:
    """Everything the reconciliation needs about a restored system.

    ``data_loss_seconds`` is (last committed transaction time − restore point); ``downtime_
    seconds`` is (recovery-complete time − outage start). Both are measured by the drill
    harness and passed in, so this module stays clock-free and deterministic.
    """

    outbox: tuple[OutboxRow, ...] = ()
    workflows: tuple[WorkflowRow, ...] = ()
    data_loss_seconds: float = 0.0
    downtime_seconds: float = 0.0


@dataclass(frozen=True)
class ReconciliationPlan:
    replay_keys: tuple[str, ...] = ()  # unpublished outbox events to re-emit
    stranded_workflows: tuple[str, ...] = ()  # mid-flight workflows needing reconciliation
    rpo_met: bool = True
    rto_met: bool = True
    data_loss_seconds: float = 0.0
    downtime_seconds: float = 0.0
    notes: tuple[str, ...] = field(default_factory=tuple)

    @property
    def clean(self) -> bool:
        """A drill passes only if targets were met AND nothing was left stranded/unreplayed.

        Replay work itself is expected and fine — the outbox is *designed* to be replayed —
        so ``replay_keys`` does not fail the drill; unmet RPO/RTO or stranded workflows do.
        """
        return self.rpo_met and self.rto_met and not self.stranded_workflows


def reconcile(snapshot: RestoreSnapshot) -> ReconciliationPlan:
    """Build the post-restore reconciliation plan and check recovery targets.

    Deterministic. Unpublished outbox rows become replay work (idempotent by key, so a
    double-run is safe — spec §6.7.6). Non-terminal workflows are flagged as stranded so a
    human/saga runner resumes or compensates them (spec §15 "workflow reconciliation").
    """
    replay_keys = tuple(r.idempotency_key for r in snapshot.outbox if not r.published)
    stranded = tuple(w.workflow_id for w in snapshot.workflows if not w.terminal)

    rpo_met = snapshot.data_loss_seconds <= RPO_SECONDS
    rto_met = snapshot.downtime_seconds <= RTO_SECONDS

    notes: list[str] = []
    if replay_keys:
        notes.append(f"{len(replay_keys)} unpublished event(s) queued for idempotent replay")
    if stranded:
        notes.append(f"{len(stranded)} workflow(s) stranded mid-flight; require reconciliation")
    if not rpo_met:
        notes.append(
            f"RPO breached: {snapshot.data_loss_seconds:.0f}s data loss exceeds {RPO_SECONDS}s"
        )
    if not rto_met:
        notes.append(
            f"RTO breached: {snapshot.downtime_seconds:.0f}s downtime exceeds {RTO_SECONDS}s"
        )

    return ReconciliationPlan(
        replay_keys=replay_keys,
        stranded_workflows=stranded,
        rpo_met=rpo_met,
        rto_met=rto_met,
        data_loss_seconds=snapshot.data_loss_seconds,
        downtime_seconds=snapshot.downtime_seconds,
        notes=tuple(notes),
    )
