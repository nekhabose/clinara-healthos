# Clinara HealthOS

**A governed clinical-workflow intelligence platform for health systems.**

> **Generative AI may communicate and assist, but governed clinical logic decides.**

Clinara HealthOS turns the flood of inbound clinical work — lab and diagnostic results,
prescription refills, and patient messages — into safe, auditable, human-reviewed
actions. Unlike an unconstrained medical chatbot, **every clinical decision is made by
deterministic, versioned, testable logic.** Large language models are used only where
they are safe: to summarize, translate, simplify, and draft communication *around* a
decision that has already been made by governed rules. If you removed the LLM entirely,
the platform would still produce a safe, complete clinical outcome.

This repository is the reference implementation. See
[`CLINARA_HEALTHOS_REQUIREMENTS.md`](./CLINARA_HEALTHOS_REQUIREMENTS.md) for the full
product and architecture specification, and [`plan.md`](./plan.md) for the phased
delivery blueprint.

---

## The problem

Clinicians drown in result-review, refill approvals, and patient-portal messages. Existing
"AI scribe / AI triage" tools either (a) stay shallow to stay safe, or (b) let a language
model make clinical judgments it cannot be trusted to make — mislabeling a critical
potassium value, silently dropping a message, or inventing a reassurance that isn't
warranted. In healthcare, a plausible-but-wrong automated action is worse than no
automation at all.

## The approach — a governed decision pipeline

Every workflow, regardless of module, flows through the same governed pipeline:

```
Ingest → Normalize (canonical model) → Patient match → Immutable context snapshot
   → Resolve effective configuration (hierarchy) → Evaluate deterministic protocol
   → [Deterministic decision produced] → LLM assists (summarize / draft / translate ONLY)
   → Output validation & safety gate → Human review (where required) → Deliver / write-back
   → Feedback capture → Analytics → Learning (governed, approval-gated)
```

Two hard invariants hold at every step:

1. **The clinical decision exists before the LLM is ever called.** The model never chooses
   classification, priority, thresholds, or actions. It is a pure function of
   *(approved template + structured facts)* — it cannot diagnose, invent facts, or weaken a
   warning.
2. **Nothing disappears silently.** Every inbound event is processed, parked in a visible
   queue (dead-letter / unknown-code / no-match), or escalated — never dropped. This is
   enforced structurally by a transactional outbox, not by convention.

## What it does (product capabilities)

| Module | What it delivers | Safety floor |
|---|---|---|
| **Results Intelligence** | Normalizes lab/diagnostic results to canonical markers, compares against history, classifies significance, drafts patient + clinician communication, routes for approval. | Critical values bypass queues and **cannot be weakened** by client/clinician config; unsupported units block interpretation. |
| **Prescription & Refill Intelligence** | Evaluates refill requests against the full clinical factor set (dose, timing, contraindications, interactions, monitoring labs, controlled-substance status). | Allergy/interaction checks are **deterministic, never LLM**; missing medication identity blocks automation; controlled substances follow a separate non-overridable path. |
| **Patient Message Intelligence** | Classifies, extracts, summarizes, prioritizes, and routes inbound patient messages; drafts approved responses. | A **deterministic red-flag detector** runs alongside model classification and can only *raise* urgency, never lower it — the system never falsely reassures. |
| **Clinical Rule Studio** | Lets clinical experts author, simulate, impact-analyze, approve, deploy (shadow → progressive), and roll back clinical logic **with no engineering release.** | Global safety constraints are engine-enforced and physically un-editable in the Studio. |
| **Analytics & Personalization** | Turns clinician edits/overrides/outcomes into governed analytics and *approval-gated* configuration recommendations. | Personalization is a **recommendation engine, not an actuator** — it can never weaken a safety constraint. |

## Why it's trustworthy (design principles)

- **Patient safety over automation rate.** A narrow workflow with 98% clinical agreement
  ships before a broad one with unpredictable behavior.
- **Rules are data, not code.** Protocols are versioned, declarative YAML artifacts
  evaluated by an engine — clinical change cadence is decoupled from software releases.
- **Everything is explainable.** Every decision produces a complete, replayable trace that
  references the exact facts and rule versions used. Context snapshots are immutable and
  hashed so any workflow can be re-run against its original inputs.
- **Everything is audited.** Every state-changing action emits an immutable, hash-chained
  audit record (actor / action / resource / tenant / before / after / reason / correlation-id).
- **Tenant isolation is defense-in-depth.** Single database, tenant-scoped rows with
  PostgreSQL Row-Level Security enforced at the connection level — an application bug
  cannot leak data across tenants. A cross-tenant access attempt is a release-blocking test
  failure.
- **PHI never leaks into logs.** Structured logging is PHI-scrubbed by middleware and
  enforced by CI lint; no chart free-text is ever passed to a model as authority.

---

## Architecture

- **Backend:** Modular monolith — Django + DRF + Pydantic — with strict module boundaries.
  Cross-module calls go through explicit service interfaces and domain events, never direct
  ORM reach-across. This preserves the option to extract services later without an early
  microservices tax.
- **Canonical contract layer:** Pydantic models are the vendor-neutral clinical contract
  shared between ingestion and workers; Django ORM models are persistence, not contracts.
- **Async spine:** Redis + Celery for standard event processing; **Temporal** is introduced
  later for long-running, human-in-the-loop, durable workflows.
- **Event bus:** Domain events written to an append-only **outbox** in the same transaction
  as the state change, then relayed to the bus — guaranteeing at-least-once, no silent loss.
- **Frontend:** Next.js + React, SSR for admin/authoring surfaces, accessibility-first
  component library, role-based navigation, and an EHR-embeddable clinician surface (SMART
  on FHIR).
- **Integration:** Adapter-per-source (HL7 v2, FHIR) with the canonical model in the middle
  — vendor quirks never leak into clinical logic.

### Monorepo layout (spec §20)

```
apps/
  api/        Django + DRF modular monolith (the backend)
  web/        Next.js admin & clinician surfaces
  workers/    Celery workers (share the api codebase)
packages/
  shared-types/     Domain event envelope, enums (Pydantic)
  clinical-models/  Canonical clinical event + immutable context snapshot (Pydantic)
  protocol-engine/  Deterministic rule engine  ← crown jewel
  integration-sdk/  HL7/FHIR adapters
  terminology/      LOINC / RxNorm / UCUM mapping
  ui/               Accessible React component library
infrastructure/
  terraform/  IaC (network, database, cache, compute, security)
  docker/     Container + compose assets
  monitoring/ OpenTelemetry / dashboards / alerts
services/     Future service-extraction targets (currently monolith modules)
docs/         architecture (ADRs), protocols, security, integrations, operations
tests/        unit, integration, clinical-regression, end-to-end, performance
```

Domain modules live in `apps/api/domains/`; each owns its models and exposes a
`services.py` interface. `packages/protocol-engine`, `packages/clinical-models`, and
`packages/terminology` are the crown-jewel assets and carry the strictest review,
versioning, and test coverage.

---

## Delivery roadmap

The platform is built as a governed sequence — each phase adds a slice without regressing
prior safety guarantees. Full detail in [`plan.md`](./plan.md).

| Phase | Focus | Status |
|---|---|---|
| **Phase 0** | **Foundation** — tenant isolation (RLS), identity & RBAC, hash-chained audit, transactional outbox, canonical contracts, PHI-safe observability. | ✅ **Implemented** |
| **Phase 1** | **Results Intelligence MVP** — the full governed pipeline end-to-end for lab results, human-approval-required. | ✅ **Implemented** |
| **Phase 2** | **Clinical Rule Studio** — author/simulate/deploy/roll-back clinical logic with no code change. | ✅ **Implemented** |
| **Phase 3** | **Production EHR Integration** — hardened HL7/FHIR ingestion, write-back, zero silent failures. | ✅ **Implemented** |
| **Phase 4** | **Prescription & Refill Intelligence** — second workflow on proven rails. | ✅ **Implemented** |
| **Phase 5** | **Patient Message Intelligence** — LLM classification under a deterministic red-flag floor. | ✅ **Implemented** |
| **Phase 6** | **Analytics & Personalization** — governed, approval-gated learning loop. | ✅ **Implemented** |
| **GA** | **GA Hardening** — kill switches, break-glass, SLO evaluation, DR reconciliation, compliance attestation, §13.5 release gate. | ✅ **Implemented** |
| **Phase 7** | **Real EMR Connectivity** — SMART-on-FHIR write-back (`Task`/`Communication`), retrying/idempotent direct-release, degraded-channel alert. Closes gaps G2 + G3 in [`gaps.md`](./gaps.md). | ✅ **Implemented** (fakes-validated; live sandbox pending) |

### Current status — Phase 1 (Results Intelligence MVP)

The full governed pipeline runs end-to-end for lab results in **human-approval-required**
mode: a FHIR result in → canonical model → immutable context snapshot → deterministic
protocol decision → validated, constrained communication draft → clinician
approve/edit/override/escalate — every step audited and replayable. Auto-delivery is
architecturally absent; critical values can never be auto-resolved.

The **deterministic clinical core is pure Python** (no framework, no database, no LLM) so it
is exhaustively unit-tested; the Django layer is a thin persistence/API shell over it.

| Phase 1 deliverable | Where |
|---|---|
| LOINC→marker mapping, UCUM normalization (unsupported unit blocks; unknown code queues) | `packages/terminology/` |
| Deterministic protocol engine + un-weakenable critical thresholds | `packages/protocol-engine/` |
| Structured result decision (spec §6.1.5) + evaluation trace | `packages/clinical-models/decision.py` |
| Versioned rule artifacts (YAML — rules are data, not code) | `clinical/protocols/` |
| Immutable, hashed context builder (spec §8.3) | `apps/api/domains/context/core.py` |
| Constrained LLM generation (approved template + facts only) | `apps/api/domains/generation/core.py` |
| Output validation & safety gate + fixed-template fallback (spec §6.9.5/6) | `apps/api/domains/safety/core.py` |
| Ingest → decide → persist → audit → events orchestration | `apps/api/domains/workflows/` |
| FHIR sandbox ingestion + idempotent raw store | `apps/api/domains/integrations/` |
| Clinician inbox + actions API (`/api/v1/workflows…`) | `apps/api/clinara/api_v1.py` |
| Operations queue (failed / unmapped events) | `apps/api/domains/operations/` |
| Golden dataset regression (spec §13.3) | `clinical/golden/` |

**Phase 0 foundation** (tenancy + RLS, identity/RBAC, hash-chained audit, transactional
outbox, canonical contracts, PHI-safe observability) underpins all of the above — see
`apps/api/core/`, `apps/api/domains/{tenants,identity,audit}/`, and `packages/shared-types/`.

### Current status — Phase 2 (Clinical Rule Studio)

Clinical experts own the logic. A clinical programmer authors a **versioned declarative
rule** (the same `Rule` shape the production engine evaluates), simulates it against
scenarios with guaranteed engine parity, reviews an **impact report** (automation /
escalation / high-risk-cohort deltas, classification changes, precedence conflicts),
routes it for **dual clinical + engineering approval**, deploys it **shadow → progressive
→ full**, and **rolls it back** — with **no application code change**. Clinical config
ships as a self-describing release bundle through a pipeline distinct from application CI/CD
(spec §14.3).

The **governed authoring mechanics are pure Python** (`domains/protocols/core.py`) so they
are exhaustively unit-tested; the Django layer is a thin persistence/API shell over them.

| Phase 2 deliverable | Where |
|---|---|
| Rule lifecycle state machine — draft → review → approved → active → rolled-back (spec §6.5.4) | `domains/protocols/core.py` (`RuleState`, `assert_transition`) |
| Simulation with engine-parity — current vs proposed over scenarios (spec §6.5.6) | `core.simulate` / `services.simulate` |
| Impact analysis before activation (spec §6.5.7) | `core.impact_report` / `services.analyze_impact` |
| Conflict detection → automation suppression, never silent resolution (spec §6.4.3) | `core.detect_conflicts` |
| Activation gate — dual approval + regression tests must pass | `services.deploy` (`_run_test_gate`, `ActivationBlocked`) |
| Un-weakenable safety floor — a rule cannot down-classify a critical | `core.assert_cannot_weaken_safety` (`SafetyViolation`) |
| Shadow / progressive / full deploy + manual & automatic rollback (spec §6.5.8) | `services.deploy` / `services.rollback`, `Deployment`/`Rollback` models |
| Self-describing config-release bundle | `services.build_release_bundle` |
| Studio API (`/api/v1/protocols…`, `/protocol-versions/…`, `/deployments/…`) | `apps/api/clinara/api_v1_protocols.py` |

### Current status — Phase 3 (Production EHR Integration)

The pipeline now survives real-world message chaos. A **hardened gateway** fronts ingestion:
it rate-limits abusive sources, guards malformed payloads, dedupes duplicates, normalizes
timestamps, and publishes canonical events — with **zero silent loss**. An **HL7 v2 adapter**
and the FHIR connection lower vendor formats to the *same* canonical payload the engine
already consumes (adapter-per-source, canonical-in-the-middle). Anything unprocessable is
**dead-lettered** (visible, replayable); replay is idempotent. **Silent-gap detection**
catches an interface that has gone quiet — a failure mode error counts never see — and
raises a critical alert. EHR **write-back / patient-portal messaging** is idempotent and
delivery-confirmed. Long-running, human-in-the-loop flows run on a **pure durable saga
runner** (pause/resume, scheduled follow-up, reverse-order compensation) — the Temporal role,
implemented deterministically so it is exhaustively testable.

| Phase 3 deliverable | Where |
|---|---|
| HL7 v2 adapter (ADT/ORU/ORM/MDM → canonical) + token bucket + gap detector (pure) | `packages/integration-sdk/` |
| Hardened gateway — malformed→dead-letter, dedup, rate-limit, timestamps (spec §6.7.4) | `domains/integrations/gateway.py` |
| Dead-letter queue + idempotent replay | `gateway.replay_dead_letter`, `DeadLetterEvent` |
| Interface health + silent-gap alerts (spec §6.7.5, §12.3) | `domains/integrations/monitoring.py` |
| Tenant-specific mappings resolved end-to-end (spec §6.7) | `terminology.IntegrationMapping` → `canonicalize(resolved_marker=…)` |
| Idempotent, confirmed EHR write-back / patient messaging (workstream 4) | `domains/delivery/` |
| Durable human-in-loop orchestration — pause/resume/timer/compensation (spec §7.6) | `domains/workflows/durable.py` |
| Gateway/monitoring/delivery + SMART-launch API | `apps/api/clinara/api_v1_integrations.py` |

### Current status — Phase 4 (Prescription & Refill Intelligence)

The **second governed clinical workflow**, on the same rails as Results Intelligence. A
refill decision is produced by a **pure deterministic engine — never an LLM**
(`domains/refills/core.evaluate_refill`): an ordered cascade that evaluates safety
exclusions *first* — missing medication identity, allergy, contraindication, drug
interaction, discontinuation, dose mismatch, controlled-substance status — and convenience
*last*. Every decision records the exact `clinical_factors_used`, so it is fully traceable
(spec §6.3.5). RxNorm identity is resolved deterministically; **missing identity blocks
automation**, **controlled substances always take a non-overridable human path**, and
**auto-approve is opt-in** to an explicitly client-approved low-risk allowlist — everything
else routes to a nurse/prescriber. The LLM only ever drafts response wording; it can never
choose an outcome or change a medication.

| Phase 4 deliverable | Where |
|---|---|
| RxNorm medication catalog + controlled-substance schedule (spec §6.3.5) | `packages/terminology/medications.py` |
| Deterministic refill engine — full factor set, ordered safety cascade (spec §6.3.2–6.3.4) | `domains/refills/core.py` |
| Refill decision traceable to exact data used (spec §6.3.5) | `RefillDecision.clinical_factors_used` → `RefillEvaluationRecord` |
| Medication/allergy/monitoring data + reviewable workflow | `domains/refills/models.py` |
| Ingest → decide → persist → audit → events; human review actions (spec §6.3.6) | `domains/refills/services.py` |
| Refill inbox + review API (`/api/v1/refills…`) | `apps/api/clinara/api_v1_refills.py` |

### Current status — Phase 5 (Patient Message Intelligence)

The most LLM-dependent module — built last, on the battle-tested deterministic scaffolding.
Inbound patient messages are stored **verbatim**, then triaged through a governed pipeline
whose defining property is a **deterministic red-flag detector as the safety floor**: the
LLM classifier may only *raise* concern above it, never lower urgency below the deterministic
result, and **model confidence alone never sets urgency** (spec §6.2.6). So an emergency
phrased inside an otherwise "administrative" message — or a prompt-injection instruction —
still escalates. The classifier is a **swappable interface** (deterministic keyword default
for hermetic tests; an LLM implements the same protocol in production). Cross-patient context
contamination is blocked **before** any chart reasoning; high-risk clinical categories are
never fully auto-resolved.

| Phase 5 deliverable | Where |
|---|---|
| Deterministic, multilingual red-flag detection over the verbatim message (spec §6.2.6) | `domains/messages/core.detect_red_flags` |
| Swappable classifier (the LLM role); confidence never sets urgency | `core.Classifier` / `RuleBasedClassifier` |
| Deterministic urgency = red-flag floor ∨ category baseline (spec §6.2.4) | `core.assign_urgency` / `most_urgent` |
| Cross-patient contamination guard before chart reasoning (spec §6.2.6) | `core.validate_identity` |
| Routing + approved-response drafting; clinical never auto-resolved | `core.route`, `services._APPROVED_RESPONSES` |
| Verbatim storage + explainable triage record + review actions | `domains/messages/{models,services}.py` |
| Patient-message inbox + review API (`/api/v1/messages…`) | `apps/api/clinara/api_v1_messages.py` |

### Current status — Phase 6 (Analytics & Personalization)

The feedback loop is closed — governed and approval-gated. Clinician actions
(approve/edit/override/escalate) are captured with **edit-difference analysis** and
aggregated into Executive / Clinical / Operations dashboards (spec §12). Personalization is a
**recommendation engine, not an actuator**: derived preferences and configuration
recommendations are **inert `pending` data** that take effect only through explicit human
approval — no endpoint applies a change autonomously. A derived preference is validated
against a safety-protected field set, so it **provably cannot weaken a safety constraint**
(spec §6.4.3). Any cross-tenant analysis is **de-identified** and small cohort cells are
**suppressed** before data leaves a tenant boundary (spec §12.5, §4.2).

| Phase 6 deliverable | Where |
|---|---|
| Edit-difference analysis + feedback aggregation (spec §12) | `domains/analytics/core.py` (`edit_difference`, `aggregate_feedback`) |
| Feedback capture (approve/edit/override/escalate), records only | `domains/feedback/` |
| Executive / Clinical / Operations dashboards (spec §12) | `analytics.services.dashboards` |
| Preference derivation that provably can't weaken safety (spec §6.4.3) | `core.derive_preferences` + `assert_preference_safe` |
| Approval-gated config recommendations (inert until approved) | `analytics.services.derive_preferences` / `approve_recommendation` |
| Cross-tenant de-identification + small-cell suppression (spec §12.5) | `core.deidentify` / `suppress_small_cells` |
| Analytics + governance API (`/api/v1/feedback`, `/api/v1/analytics…`) | `apps/api/clinara/api_v1_analytics.py` |

---

### Current status — Phase 7 (Real EMR Connectivity)

The write-back edge is now **real**, not a stub. An approved result is delivered at **direct
release** the way Elaborate does it: a **patient-portal message** (FHIR `Communication`) plus a
**care-team inbasket task** (FHIR `Task`), written to the EMR over an authenticated
SMART-on-FHIR connection. This closes gaps **G2** (SMART Backend Services auth) and **G3**
(Epic/Athena write-back adapters) from [`gaps.md`](./gaps.md).

The design follows the same discipline as every phase: a **pure, dependency-injected** adapter
core in `clinara_integration_sdk` (the HTTP transport, the JWT signer, and the clock are all
injected), with the Django `domains/delivery` layer keeping every governance guarantee. Because
the transport and signer are injected, the entire flow is **validated against a
vendor-emulating token + FHIR server today** and points at a live Epic/Athena endpoint by
configuration alone (`EHR_WRITE_BACK`) — no code change. Dev/test signs assertions with an
`HmacSigner`; production injects an **RS384 signer** over a vault-held key (the flow is
identical either way). *Validation is against conformance fakes; live-sandbox certification and
the HL7 v2 MLLP listener are the remaining GA steps for this phase.*

Safety and governance are preserved throughout:

- **Confirmed delivery with bounded retry.** Transient failures (`429`/`5xx`/network) are
  retried with backoff (injected sleeper → deterministic); a terminal `4xx` fails fast. Every
  attempt is recorded and the terminal outcome emits `DeliverySucceeded`/`DeliveryFailed` —
  **zero silent loss**.
- **Idempotent direct release.** `release_result` produces **exactly one** portal message and
  **one** EHR task per approved workflow; re-releasing is a no-op — duplicate patient
  communication is a clinical-safety event and is structurally prevented.
- **Degraded-channel operator alert.** A write-back failure spike raises a `WriteBackDegraded`
  signal, surfaced via `delivery/health`.
- **Canonical-in-the-middle.** The adapter speaks only FHIR; vendor quirks live in `EPIC` /
  `ATHENA` profiles and never leak into protocol logic. Bearer tokens are fetched once and
  reused until near expiry.

| Phase 7 deliverable | Where |
|---|---|
| SMART Backend Services auth (client-assertion JWT, token cache/refresh, scopes) | `packages/integration-sdk/clinara_integration_sdk/smart.py` |
| FHIR R4 write-back client (`Task` + `Communication`, id extraction, Epic/Athena profiles, retryable-vs-terminal) | `packages/integration-sdk/clinara_integration_sdk/fhir_writeback.py` |
| Injectable HTTP transport (stdlib `UrllibTransport`) + pure retry policy | `…/transport.py`, `…/retry.py` |
| `SmartEhrClient` bridging the delivery `EhrClient` seam to FHIR write-back | `apps/api/domains/delivery/adapters.py` |
| Retrying/confirmed `deliver`, idempotent `release_result`, `write_back_health` + degraded alert | `apps/api/domains/delivery/services.py` |
| Release + delivery-health API (`/api/v1/workflows/{id}/release`, `/api/v1/delivery/health`) | `apps/api/clinara/api_v1_integrations.py` |
| Per-vendor endpoint config (env-backed, secrets stay in the vault) | `clinara/settings/base.py` + `production.py` (`EHR_WRITE_BACK`) |
| Tests (SMART flow, FHIR write-back, retry, end-to-end delivery/release/alert/token reuse) | `packages/integration-sdk/tests/test_{smart,fhir_writeback,retry}.py`, `apps/api/tests/test_phase7_smart_delivery.py` |

---

### Current status — GA Hardening (compliance, resilience, scale, release gate)

The five GA focus areas are delivered as governed platform mechanics with the same discipline
as every phase: a pure, Django-free decision core (exhaustively unit-tested), a thin Django
layer (persistence + audit + outbox), and — where operational — a runbook, Terraform, and
blocking CI wiring. **Emergency controls, reliability, DR, and compliance are all-or-nothing
and fail-closed:** a broader kill switch is never overridden by a narrower one; break-glass is
time-boxed, reason-mandatory, and always audited; a missing SLO metric is a breach, not a pass;
a DR drill fails loudly if RTO/RPO are missed or a workflow is stranded; attestation is refused
on any completeness gap; and the release gate blocks unless all eight §13.5 conditions hold.
The genuinely external, process-bound items (a third-party SOC 2 Type II audit, a live pen-test,
a live cloud DR game-day, sustained production load) are delivered as the code, drills, gates,
and runbooks that make them executable — never asserted as complete.

| GA deliverable | Where |
|---|---|
| Kill switches across all 10 scopes (spec §11.4), broadest-wins, deny-on-ambiguity | `domains/killswitch/core.py` (`resolve`); `services.engage/release/check` |
| LLM provider failover honoring the kill switch (spec §11.4) | `domains/reliability/core.py` (`select_provider`); `services.choose_provider` |
| Break-glass emergency access — time-boxed, reason-mandatory, audited (spec §10.2) | `domains/identity/breakglass.py`; `identity.services.grant/revoke_break_glass` |
| SLO evaluation over the full spec §12.4 set + breach ledger | `domains/reliability/core.py` (`evaluate_slos`); `services.evaluate_and_record` |
| DR reconciliation — replay + stranded workflows + RTO/RPO check (spec §15) | `domains/continuity/core.py` (`reconcile`); `services.run_drill`; `docs/runbooks/disaster-recovery.md` |
| Multi-AZ + PITR + versioned encrypted backups (spec §15) | `infrastructure/terraform/modules/database/main.tf` |
| Compliance attestation — audit/access/decision-trace completeness (spec §10.1) | `domains/compliance/core.py` (`build_attestation`); `docs/compliance/` |
| §13.5 release gate — fail-closed, all 8 conditions, wired into CI | `apps/api/core/release_gate.py`; `scripts/release_gate.py`; `release-gate` CI job |

**All six delivery phases plus GA hardening are implemented.** Run the tests: `cd apps/api &&
pytest` (results + Rule Studio + gateway + delivery + refills + messages + analytics + GA
services + API + app-layer isolation on SQLite); `PYTHONPATH=apps/api pytest packages tests/unit
tests/clinical-regression` (the deterministic clinical core + Studio/HL7/durable/refill/triage/
analytics core + kill-switch/reliability/continuity/compliance/release-gate/break-glass cores +
golden dataset). PostgreSQL RLS is verified by the `rls` CI job; the §13.5 gate by `release-gate`.

---

## Quick start (local)

Requires Docker (Postgres + Redis) for the full stack.

```bash
cp .env.example .env
make up          # docker compose: postgres, redis, api, worker, web
make migrate     # apply Django migrations
make test        # run the test suite (incl. the tenant-isolation harness)
```

Common tasks: `make lint` (ruff + mypy), `make worker` (Celery), `make shell` (Django shell).
See the [`Makefile`](./Makefile) for the full list.

## Engineering guardrails (enforced every phase)

1. Patient safety over automation rate.
2. Governed logic decides; AI assists — the deterministic decision always precedes and
   constrains generation.
3. Nothing silent — outbox, dead-letter, unknown-code queues, and gap detection are
   foundational, not features.
4. Tenant isolation is a release-blocking test.
5. Every state change is audited; every decision is replayable.

---

## License & status

Reference implementation, under active development. Not a certified medical device and not
for clinical use in its current state. See the requirements spec for the intended
compliance posture (HIPAA, SOC 2 Type II, HITECH).
