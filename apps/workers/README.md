# @clinara/workers

Celery workers run against the **same codebase** as `apps/api` (the modular monolith),
not a separate service. This directory documents how workers are deployed; the code lives
in `apps/api` and is discovered via `clinara.celery`.

```bash
# Run a worker
celery -A clinara.celery worker -l info

# Run the beat scheduler (drives the outbox relay — spec §7.5)
celery -A clinara.celery beat -l info
```

Worker types (grown per phase):
- **event workers** — Results / Messages / Rx processing (Phase 1, 4, 5)
- **outbox relay** — publishes committed domain events to the bus (Phase 0)
- **durable workflows** — Temporal is introduced in Phase 3 for long-running, human-in-loop
  flows (scheduled follow-ups, multi-day refills); Celery covers Phases 0–2.
