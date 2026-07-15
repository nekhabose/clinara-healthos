# Business Continuity (GA hardening — spec §15)

Proves the platform loses no committed work and strands no workflow after a restore, and that
recovery met the RTO/RPO targets.

| File | Responsibility |
|---|---|
| `core.py` | Pure: `reconcile(snapshot) -> ReconciliationPlan`. Finds unpublished outbox events to replay (idempotent), flags stranded mid-flight workflows, and checks RPO/RTO explicitly. Unit-tested in `tests/unit/test_continuity_core.py`. |
| `models.py` | `DisasterRecoveryDrill` — auditable history of each restore drill. |
| `services.py` | `run_drill(snapshot, label)` — reconcile, persist outcome, publish `DisasterRecoveryReconciled`. |

**Targets (spec §15):** RTO 4h core services, RPO 15min transactional data. A drill passes
only if targets were met **and** nothing is stranded; replay work alone does not fail it (the
outbox is designed to be replayed).

See `docs/runbooks/disaster-recovery.md` for the operational restore + reconciliation
procedure.
