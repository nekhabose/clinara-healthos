# Reliability (GA hardening — spec §12.4, §11.4)

Two GA gates: proving the platform meets its SLOs, and failing LLM providers over safely.

| File | Responsibility |
|---|---|
| `core.py` | Pure: `evaluate_slos(observed) -> SLOReport` over the full spec §12.4 objective set, and `select_provider(preference, health, switches) -> ProviderSelection`. A missing metric is a breach, not a pass. Unit-tested in `tests/unit/test_reliability_core.py`. |
| `models.py` | `SLOBreachRecord` — durable breach history for the ops dashboard and release gate. |
| `services.py` | `evaluate_and_record` (persist + publish `SLOBreached`) and `choose_provider` (failover, consulting the live kill-switch set). |

**SLOs enforced (spec §12.4):** ingestion availability 99.9%, routine < 2min (99%), critical
< 30s (99%), zero silent message loss, audit recording 99.9%, approved-channel delivery 99%,
decision-trace availability 100%.

**Provider failover** returns the first healthy, un-killed provider in preference order and
records why each skipped one was passed over. `provider=None` means every candidate is down or
killed — the caller must fall back to the deterministic/no-LLM path, never proceed blind.
