# Kill Switch (GA hardening — spec §11.4)

The platform's automation emergency brake. A switch active at **any** of the ten spec §11.4
scopes suppresses automation for everything inside it.

| File | Responsibility |
|---|---|
| `core.py` | Pure, Django-free resolver: `resolve(attempt, switches) -> KillSwitchDecision`. Broadest-scope-wins, deny-on-ambiguity, fully explainable. Unit-tested in `tests/unit/test_killswitch_core.py`. |
| `models.py` | `KillSwitchRecord` — the active switch set (platform-level, not tenant-RLS-scoped; one active row per scope+target). |
| `services.py` | `engage` / `release` (audited + event-published) and `check` / `automation_allowed` (the read path automation calls before acting). |

**Scopes (broadest → narrowest):** global, tenant, site, specialty, workflow, protocol,
clinician, model_provider, integration, communication_channel.

**Design invariants**
- A broader switch is never overridden by a narrower one (a GLOBAL disable is absolute).
- An attempt that cannot be fully attributed is *suppressed*, never waved through.
- Every suppression names the exact scope/target that caused it, for the decision trace.

**LLM kill switch across all scopes** — `core.llm_provider_suppressed` and the
`reliability.select_provider` failover chain both consult this module, so a provider under a
MODEL_PROVIDER (or GLOBAL) switch is transparently skipped.
