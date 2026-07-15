# Architecture

Source of truth: [`../../CLINARA_HEALTHOS_REQUIREMENTS.md`](../../CLINARA_HEALTHOS_REQUIREMENTS.md)
and the phased plan [`../../plan.md`](../../plan.md).

## The governed decision pipeline (the backbone)

```
Ingest → Normalize (canonical model) → Patient match → Build immutable context snapshot
  → Resolve effective configuration → Evaluate deterministic protocol
  → [Decision exists] → LLM assists (summarize / draft / translate ONLY)
  → Output validation & safety gate → Human review → Deliver / write-back
  → Feedback → Analytics → Governed learning
```

Two invariants hold at every step:

1. **The clinical decision exists before the LLM is ever called.** Remove the LLM and the
   workflow still produces a safe, deterministic outcome.
2. **Nothing disappears silently.** Every event is processed, parked in a visible queue,
   or escalated — never dropped (transactional outbox + dead-letter + gap detection).

## Phase 0 building blocks in this repo

- Modular monolith with per-domain boundaries → `apps/api/domains/` (see its README).
- Canonical contracts (Pydantic) → `packages/clinical-models`, `packages/shared-types`.
- Tenant isolation via PostgreSQL RLS → `apps/api/core/rls.py`, `clinara/middleware/tenant.py`.
- Transactional outbox → `apps/api/core/outbox.py`, `apps/api/core/tasks.py`.
- Immutable audit → `apps/api/domains/audit/`.
- PHI-safe structured logging → `clinara/middleware/phi_safe_logging.py`.

## Decision records

See [`adr/`](./adr/).
