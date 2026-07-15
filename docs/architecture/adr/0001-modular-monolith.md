# ADR 0001: Modular monolith with data-layer tenant isolation

- **Status:** Accepted
- **Date:** 2026-07 (Phase 0)
- **Context sources:** requirements §7.3, §7.4; plan §1.2

## Context

The spec recommends a modular monolith initially, with logical services extracted only
when scaling/isolation/ownership/reliability justify it (§7.3). We also must guarantee
strict tenant isolation for PHI across all customers.

## Decision

1. **Modular monolith** in `apps/api`. Domain modules live under `domains/` (renamed from
   the spec's `apps/` to avoid colliding with the repo-root `apps/` deployables). Each
   module owns its models and exposes a `services.py` interface; cross-module calls go
   through interfaces and explicit domain events — never direct ORM reach-across.
2. **`services/` extraction targets** (integration-gateway, workflow-orchestrator,
   communication-service) exist as directories now but are implemented as monolith modules
   until extraction is justified.
3. **Tenant isolation at the database** via PostgreSQL Row-Level Security, not app-layer
   filtering alone. The app connects as a non-superuser role; every tenant-scoped table
   gets a `tenant_isolation` policy (`core/rls.py`) keyed on the `app.current_tenant`
   session var set per request (`clinara/middleware/tenant.py`). App-layer scoping is
   defense in depth on top.
4. **Transactional outbox** for domain events so a crash can never lose an event (§7.5).

## Consequences

- Extraction later is cheap because boundaries are explicit from day one.
- A logic bug cannot leak cross-tenant data because RLS is enforced by the database.
- Every mutating path must run inside a tenant-pinned DB session; background jobs must set
  the tenant explicitly before touching tenant data.
