"""Durable, replayable workflow orchestration (plan Phase 3, workstream 5).

Long-running clinical flows need durability that stateless Celery tasks don't provide:
they pause for human review for hours, schedule follow-ups days out, time out, and must
*compensate* (undo) partial work on failure. In production this is Temporal (plan §1.2);
here the same governed semantics are implemented as a **pure, deterministic saga runner** so
the orchestration contract is exhaustively unit-testable without a durable-execution
backend.

Determinism is the point: a saga's ``journal`` records every completed step's output, so a
paused/scheduled saga resumes by *replaying* the journal (never re-running side effects) and
continuing from the pending step — exactly Temporal's replay model.

Control signals a step may raise:
  * ``HumanReviewPause`` — suspend until a clinician acts (spec §7.6 human-in-loop pause).
  * ``ScheduledFollowUp`` — suspend until a due time (scheduled follow-up / timer).
On an unhandled exception, completed steps are compensated in reverse order.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any


class HumanReviewPause(Exception):
    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


class ScheduledFollowUp(Exception):
    def __init__(self, due_epoch: float, reason: str = "") -> None:
        self.due_epoch = due_epoch
        self.reason = reason
        super().__init__(reason)


@dataclass(frozen=True)
class Step:
    name: str
    run: Callable[[dict[str, Any]], Any]
    compensate: Callable[[dict[str, Any]], None] | None = None


@dataclass
class SagaResult:
    status: str  # completed | paused | scheduled | failed
    journal: dict[str, Any] = field(default_factory=dict)
    pending_step: str | None = None
    failed_step: str | None = None
    error: str | None = None
    reason: str | None = None
    due_epoch: float | None = None
    compensated: list[str] = field(default_factory=list)

    @property
    def is_terminal(self) -> bool:
        return self.status in {"completed", "failed"}


def run_saga(steps: list[Step], *, journal: dict[str, Any] | None = None) -> SagaResult:
    """Run (or resume) a saga. Completed steps present in ``journal`` are replayed, not re-run.

    Resuming is simply calling ``run_saga`` again with the prior result's ``journal`` (plus
    any resume input merged in) — the runner skips steps already journaled and continues.
    """
    journal = dict(journal or {})
    completed: list[Step] = [s for s in steps if s.name in journal]

    for step in steps:
        if step.name in journal:
            continue  # already done in a previous run — replay, don't re-execute
        try:
            journal[step.name] = step.run(journal)
            completed.append(step)
        except HumanReviewPause as pause:
            return SagaResult(status="paused", journal=journal,
                              pending_step=step.name, reason=pause.reason)
        except ScheduledFollowUp as sched:
            return SagaResult(status="scheduled", journal=journal,
                              pending_step=step.name, due_epoch=sched.due_epoch,
                              reason=sched.reason)
        except Exception as exc:  # noqa: BLE001 — any failure triggers governed compensation
            compensated: list[str] = []
            for done in reversed(completed):
                if done.compensate is not None:
                    done.compensate(journal)
                    compensated.append(done.name)
            return SagaResult(status="failed", journal=journal, failed_step=step.name,
                              error=str(exc), compensated=compensated)

    return SagaResult(status="completed", journal=journal)


def resume(steps: list[Step], prior: SagaResult, *, resume_input: dict[str, Any] | None = None,
           now_epoch: float | None = None) -> SagaResult:
    """Resume a paused/scheduled saga. A scheduled saga only proceeds once its due time passed."""
    if prior.status == "scheduled" and prior.due_epoch is not None:
        if now_epoch is None or now_epoch < prior.due_epoch:
            return prior  # timer not yet due — stay suspended (deterministic)
    journal = dict(prior.journal)
    if resume_input:
        journal.update(resume_input)
    return run_saga(steps, journal=journal)


__all__ = [
    "Step", "SagaResult", "run_saga", "resume", "HumanReviewPause", "ScheduledFollowUp",
]
