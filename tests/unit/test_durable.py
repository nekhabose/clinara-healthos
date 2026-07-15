"""Pure durable saga orchestration (plan Phase 3, workstream 5).

Runs with PYTHONPATH=apps/api, Django-free. Proves the Temporal-role semantics:
deterministic replay, human-review pause/resume, scheduled follow-up timers, and
reverse-order compensation on failure.
"""
from domains.workflows.durable import (
    HumanReviewPause,
    ScheduledFollowUp,
    Step,
    resume,
    run_saga,
)


def test_saga_runs_to_completion_and_journals():
    steps = [
        Step("normalize", lambda j: {"marker": "a1c"}),
        Step("decide", lambda j: {"classification": "clinician_review_required"}),
    ]
    result = run_saga(steps)
    assert result.status == "completed"
    assert result.journal["decide"]["classification"] == "clinician_review_required"


def test_human_review_pause_and_resume_replays_journal():
    calls = []
    steps = [
        Step("build_context", lambda j: calls.append("build") or {"ok": True}),
        Step("await_review", lambda j: (_ for _ in ()).throw(HumanReviewPause("clinician"))),
        Step("deliver", lambda j: calls.append("deliver") or {"delivered": True}),
    ]
    paused = run_saga(steps)
    assert paused.status == "paused"
    assert paused.pending_step == "await_review"

    # Resume: the completed step is NOT re-run (replayed from journal); provide review input.
    resumed = resume(
        [
            Step("build_context", lambda j: calls.append("build") or {"ok": True}),
            Step("await_review", lambda j: {"approved": True}),  # now resolves
            Step("deliver", lambda j: calls.append("deliver") or {"delivered": True}),
        ],
        paused,
        resume_input={"await_review": {"approved": True}},
    )
    assert resumed.status == "completed"
    assert calls == ["build", "deliver"]  # build ran once, not twice


def test_scheduled_follow_up_waits_until_due():
    steps = [
        Step("schedule", lambda j: (_ for _ in ()).throw(ScheduledFollowUp(due_epoch=100.0))),
        Step("follow_up", lambda j: {"done": True}),
    ]
    scheduled = run_saga(steps)
    assert scheduled.status == "scheduled"
    assert scheduled.due_epoch == 100.0

    # Not yet due → still suspended.
    still = resume(
        [Step("schedule", lambda j: {}), Step("follow_up", lambda j: {"done": True})],
        scheduled, now_epoch=50.0,
    )
    assert still.status == "scheduled"

    # Past due → proceeds.
    done = resume(
        [Step("schedule", lambda j: {}), Step("follow_up", lambda j: {"done": True})],
        scheduled, now_epoch=150.0,
    )
    assert done.status == "completed"


def test_failure_compensates_completed_steps_in_reverse():
    undone = []
    steps = [
        Step("reserve", lambda j: {"reserved": True},
             compensate=lambda j: undone.append("reserve")),
        Step("charge", lambda j: {"charged": True},
             compensate=lambda j: undone.append("charge")),
        Step("ship", lambda j: (_ for _ in ()).throw(RuntimeError("carrier down"))),
    ]
    result = run_saga(steps)
    assert result.status == "failed"
    assert result.failed_step == "ship"
    assert result.error == "carrier down"
    assert undone == ["charge", "reserve"]  # reverse order
    assert result.compensated == ["charge", "reserve"]
