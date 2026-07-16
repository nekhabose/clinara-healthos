# domains/specialties — Specialty Protocol Breadth (Phase 10, closes gap G6)

Grows Clinara's authored, clinically-validated protocol **content** from the ~6 Phase 1 lab
markers to **30+ ambulatory specialties**, and adds **per-tenant threshold customization with
no code change** — while preserving the §1 invariant: *no model-driven clinical decision*.
Every suggestion here is deterministic logic over data.

This is a **content + governance** phase, not an engine change. The crown-jewel evaluator
(`clinara_protocol_engine`) is untouched; breadth is delivered as:

- **Catalog data** — `clinara_terminology` gained 19 markers (thyroid, extended lipids,
  hepatic, hematology, coagulation, inflammatory, electrolytes). `LAB_FACT_ALIAS` is now
  *derived* from `MARKER_SPECS`, so adding a marker is a pure data change.
- **Parameterized protocol packs** — `clinical/protocols/specialties/*.yaml`. Specialty-scoped,
  deterministic rules whose thresholds are `{param: <name>}` placeholders with pack defaults.
- **This domain** — the registry, the pack activation gate, and the governed threshold policy.

## Layout

| File | Responsibility |
|---|---|
| `catalog.py` | The 34-specialty ambulatory registry (`AMBULATORY_SPECIALTIES`) as data. |
| `core.py` | Pure, Django-free pack mechanics: load, **`bind_parameters`**, `validate_pack`, `coverage`. |
| `services.py` | Governed layer: pack library, `SpecialtyThresholdPolicy`, `set_threshold` (gated), `resolve_rules`. |
| `models.py` | `SpecialtyThresholdPolicy` — per-tenant, RLS-isolated threshold overrides. |

## The two exit-gate guarantees

1. **Every pack passes the Rule Studio activation gate.** `validate_pack` binds every rule,
   asserts no rule down-classifies a critical value (`assert_cannot_weaken_safety`), and runs
   every required test case (`run_test_cases`) — the same gate `domains/protocols` enforces at
   deploy. `services.validate_all()` proves it for the whole library; `coverage_report()` proves
   all 34 registered specialties are served by ≥1 active rule.

2. **Per-tenant threshold customization can never weaken safety.** `set_threshold`
   re-validates the *whole pack* with the proposed override before persisting it. An override
   that would down-classify a critical value, break a required test, or name an undeclared
   parameter is rejected (`ThresholdRejected` → HTTP 422). The override is data applied by
   `bind_parameters` at rule-load time — no rule YAML is edited, no code ships. `resolve_rules`
   composes base rules + tenant-bound packs into the exact, replayable set the engine evaluates.

## Safety ordering is still un-weakenable

Pack rules are authored bounded *above* the hard critical floor (`clinara_protocol_engine.
critical`), which the engine evaluates FIRST. A critical value (e.g. Hgb < 6, INR > 5, Na < 120)
escalates before any pack rule runs; the pack rules literally cannot match it. The pack test
suites include critical-value cases asserting exactly this.

## API (`/api/v1/specialties/*`)

- `GET  /specialties` — registry + coverage report.
- `GET  /specialties/packs` — the validated pack library.
- `GET  /specialties/packs/{key}` — pack detail + this tenant's effective thresholds.
- `POST /specialties/packs/{key}/thresholds` — override a threshold (gated; 422 if unsafe).
- `POST /specialties/packs/{key}/thresholds/reset` — clear overrides to pack defaults.
