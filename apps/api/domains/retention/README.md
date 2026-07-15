# domains/retention — Data Lifecycle & Compliance Hardening (Phase 11, closes G7)

Minimal-necessary **data retention** and **purge** with a BAA-termination hard-purge and a
tamper-evident **certificate of destruction**. This is the compliance-lifecycle half of the
Elaborate parity work: *"Minimal necessary data retained for 90 days; fully purged on
termination per BAA."*

## Boundary rules

- Other modules interact with this domain **only** through `services.py`.
- This domain is the cross-cutting data-lifecycle owner, so — uniquely — its service reaches
  directly into other domains' models to destroy expired rows (`services.PURGE_TARGETS`).
- The pure retention/purge logic lives in `core.py` (Django-free, exhaustively unit-testable);
  the codified retention schedule lives in `catalog.py` (data, not code).

## What it does

- **Per-tenant retention policy** (`RetentionPolicy`) — catalog defaults overlaid with
  per-category overrides, validated against hard bounds so a window is never zero or unbounded.
- **Scheduled minimization** (`run_scheduled_purge` / Celery beat + `purge_expired` command) —
  sweeps every *windowed* PHI category past its per-tenant window. Deterministic, idempotent,
  tenant-scoped. `dry_run=True` reports counts without deleting (proof of scope).
- **BAA-termination hard-purge** (`terminate_tenant`) — destroys *all* of a tenant's PHI and
  issues a `CertificateOfDestruction` with a content hash verifiable against `core`.

## Invariants held

- **Deterministic & bounded** — what is purged is a pure function of (policy, clock, data).
- **Tenant-scoped** — every purge binds the RLS tenant and filters `tenant_id`; it can never
  cross a tenant boundary.
- **Audit trail preserved** — `AuditEvent` is append-only and is never a purge target; every
  purge appends one hash-chained `data_purge` record and the certificate counts the audit events
  retained, proving the trail survived.

## Events

`RetentionPolicyUpdated`, `DataPurged` (scheduled), `TenantDataPurged` (termination) — all via
the transactional outbox in the same commit as the purge.
