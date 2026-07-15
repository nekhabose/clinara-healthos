# Security & Compliance

Targets: HIPAA, SOC 2 Type II, HITECH, state privacy laws, BAAs (spec §10.1).

## Phase 0 controls in this repo

| Control | Implementation |
|---|---|
| Tenant isolation | PostgreSQL RLS (`apps/api/core/rls.py`) + tenant middleware |
| Least-privilege DB | App connects as non-superuser `clinara_app` role |
| PHI-safe logging | `clinara/middleware/phi_safe_logging.py` (scrub + structured JSON) |
| Immutable audit | Hash-chained `AuditEvent` (`domains/audit/`) |
| Secrets | AWS Secrets Manager (prod); `.env` for local only |
| Encryption | TLS in transit; KMS at rest (Terraform); enforced in `settings/production.py` |
| Non-root containers | `apps/api/Dockerfile` runs as `appuser` |

## RLS pattern

Every tenant-scoped table must, in a migration:

```python
from core.rls import enable_rls
operations = [enable_rls("<table_name>")]
```

RLS is only effective because the app role is **not** a superuser and does not own the
tables (owners bypass RLS). The tenant-isolation test suite (`tests/integration/`) is a
release-blocking gate: any cross-tenant read/write is a failure.

## Auditable actions (spec §10.4)

authentication · PHI access · rule create/modify/approve/deploy · config change · mapping
change · workflow decision · LLM usage · message delivery · clinician action · admin export
· support access · data purge.

Each record carries: actor, action, resource, tenant, timestamp, source IP, session,
before/after state, reason, correlation id — plus the tamper-evidence chain.
