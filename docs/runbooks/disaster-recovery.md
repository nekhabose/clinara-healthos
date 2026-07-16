# Runbook — Disaster Recovery & Business Continuity (spec §15)

Operational procedure for restoring Clinara HealthOS after data loss or a regional outage, and
for the **quarterly restore drill** the spec mandates.

## Targets

| Objective | Target | Enforced by |
|---|---|---|
| RTO (core services) | **4 hours** | `continuity.core.RTO_SECONDS`; drill fails if exceeded |
| RPO (transactional) | **15 minutes** | `continuity.core.RPO_SECONDS`; drill fails if exceeded |

Both are checked automatically — a drill that misses either target is recorded as `failed`, not
quietly passed.

## Infrastructure posture (Terraform — `infrastructure/terraform/modules/database`)

- **Multi-AZ** synchronous standby → automatic failover with no data loss on AZ failure.
- **Automated backups + PITR** (`backup_retention_period = 14d`) → restore to any point within
  retention at ~5-min granularity (meets the 15-min RPO).
- **Encryption at rest** (KMS) on the instance and the versioned backup bucket.
- **S3 versioning** on the backup bucket; optional **cross-region** automated-backup replication
  (`cross_region_backup = true`) where a customer contract requires it.

## Recovery procedure

1. **Declare** the incident; start the outage clock (drives the RTO measurement).
2. **Choose the recovery point.** For corruption/bad-deploy: PITR to just before the event. For
   AZ loss: Multi-AZ failover is automatic — verify the standby was promoted.
3. **Restore** the RDS instance (PITR or latest snapshot) into the target environment.
4. **Provision the app role** and apply migrations (idempotent) if restoring into fresh infra.
5. **Reconcile** — run the continuity drill against the restored DB. It:
   - finds committed-but-unpublished outbox events and hands them to the **outbox relay** for
     **idempotent replay** (double-runs are safe — dedup by `idempotency_key`);
   - flags **stranded mid-flight workflows** for the **durable saga runner** to resume/compensate;
   - checks the achieved **RPO/RTO** against target.
6. **Verify** SLOs (`reliability.evaluate_and_record`) and that the decision-trace availability
   SLO is back to 100% before resuming automation.
7. **Manual-operations fallback** — if automation cannot be safely resumed, engage the relevant
   **kill switches** (`killswitch.engage`) so clinicians work the queues manually while the
   platform recovers. Nothing is lost — everything remains in the visible ops queues.

## Running the drill (quarterly)

```python
from domains.continuity import services as continuity
from domains.continuity.core import RestoreSnapshot, OutboxRow, WorkflowRow

snapshot = RestoreSnapshot(
    outbox=(...),          # from the restored DB
    workflows=(...),       # from the restored DB
    data_loss_seconds=...,  # measured: last commit − restore point
    downtime_seconds=...,   # measured: recovery-complete − outage start
)
drill = continuity.run_drill(snapshot, label="2026-Q3")
assert drill.outcome == "passed"   # gate the drill result in CI/ops
```

The drill persists a `DisasterRecoveryDrill` row and emits `DisasterRecoveryReconciled`. A
recent **passing** drill is a release-gate input (observability/rollback readiness).

## Post-incident

- Confirm every replayed event reached the bus and every stranded workflow was resolved.
- File the audit trail (grants, kill-switch engagements, drill record) with the incident review.
