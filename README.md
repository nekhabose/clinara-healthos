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
  integration-sdk/  HL7/FHIR adapters, SMART-on-FHIR auth + EHR launch, write-back
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
| **Phase 8** | **EHR-Embedded Clinician Surface** — SMART-on-FHIR EHR launch + OIDC identity bridge (no separate login), clinician chart-context panel, embedded surface, Epic/Athena marketplace manifests. Closes gaps G4 + G5 in [`gaps.md`](./gaps.md). | ✅ **Implemented** (fakes-validated; live marketplace pending) |
| **Phase 9** | **Billing & Coding Intelligence** — deterministic revenue-integrity module: documented-uncoded / HCC-gap / specificity-upgrade detectors over the canonical snapshot, evidence-linked, human-confirmed review queue, export-gated on confirmation, acceptance/override fed into the Phase 6 loop. Closes gap G1 in [`gaps.md`](./gaps.md). | ✅ **Implemented** |
| **Phase 10** | **Specialty Protocol Breadth** — canonical catalog grown to 25 markers; 7 validated, parameterized protocol packs covering 34 ambulatory specialties; per-tenant threshold customization bound as data at load time and gated so it can never weaken safety. No engine change. Closes gap G6 in [`gaps.md`](./gaps.md). | ✅ **Implemented** |

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

### Current status — Phase 8 (EHR-Embedded Clinician Surface)

Where Phase 7 gave Clinara the outbound edge (write-back *to* the EMR), Phase 8 gives it the
inbound edge: a clinician now opens Clinara **from inside** their EHR and is signed in without a
separate login. This closes gaps **G4** (EHR-embedded surface) and **G5** (chart-context panel)
from [`gaps.md`](./gaps.md), matching Elaborate's "built directly into your EMR — no new
platforms, no extra clicks, no additional logins" distribution.

The full **SMART App Launch (EHR launch)** sequence is implemented as a **pure, dependency-
injected** flow in `clinara_integration_sdk/smart_launch.py`: the app discovers the EHR's
endpoints from `/.well-known/smart-configuration`, redirects the browser to the EHR authorize
endpoint (`aud`/`state`/`nonce`/`launch`), exchanges the returned `code` for tokens, and — the
security-critical step — validates the OIDC `id_token` with **each check independently
enforced**: the signature (via an injected `Verifier`), `iss`, `aud`, `exp`, and `nonce`
(alg-confusion + replay guards). The HTTP transport, the JWT verifier, the clock, and the
state/nonce factories are all injected, so the whole flow is **validated against a
vendor-emulating fake EHR today** and points at a live Epic/Athena endpoint by configuration
alone. Dev/test verifies id_tokens with an `HmacVerifier`; production injects an **RS256/JWKS
verifier** (the flow is identical either way). *Validation is against conformance fakes; a live
Epic Showroom / Athena Marketplace listing and the JWKS verifier are the remaining GA steps.*

Identity, isolation, and audit are preserved throughout — the bridge **reuses**
`domains/identity`, it does not fork it:

- **Fail-closed identity bridge.** A launch completes only if the EHR clinician identity
  (`fhirUser`/`sub`) resolves to a Clinara `User` via an `EhrIdentityLink` **within the issuer's
  tenant**. No link ⇒ the launch is refused (never bridged to a default account). Every launch —
  bridged or denied — is audited and emits `EhrLaunched`/`EhrLaunchDenied`.
- **Tenant isolation at the database.** The issuer→tenant routing (`EhrConnection`) and the
  `state`-keyed handshake (`EhrLaunchSession`) are resolved *before* any tenant context exists
  (the launch is unauthenticated), so they sit outside the per-tenant RLS policy by design; the
  identity link — resolved *after* the tenant is bound — **is** RLS-enforced. A link in tenant A
  can never satisfy a launch that resolved to tenant B.
- **No separate login; session expires with the EHR.** The callback establishes the Django
  session directly and caps its lifetime at the EHR token's `expires_in`, so the embedded
  session cannot outlive the EHR session; a lapsed session transitions to `EXPIRED`.
- **Chart-context panel (G5) adds nothing.** `build_context_panel` is a pure, presentation-only
  projection of the immutable `ContextSnapshot` the engine already reasoned over — labs
  (value/unit/reference range/trend + in/below/above-range status), patient context, and
  provenance/freshness — rendered beside the item under review so there is no chart digging.

| Phase 8 deliverable | Where |
|---|---|
| SMART App Launch flow (discovery, authorize URL, code exchange, OIDC id_token validation) | `packages/integration-sdk/clinara_integration_sdk/smart_launch.py` |
| Injected id_token `Verifier` (`HmacVerifier` dev / RS256-JWKS prod) | `…/smart_launch.py`, `apps/api/domains/embedded/adapters.py` |
| Persistence + identity bridge (`EhrConnection`, `EhrIdentityLink` [RLS], `EhrLaunchSession`) | `apps/api/domains/embedded/models.py` |
| `begin_launch` / `complete_launch` (fail-closed bridge, audited, event-published, token-bounded session) | `apps/api/domains/embedded/services.py` |
| Chart-context panel (G5) — pure builder + snapshot read service | `apps/api/domains/context/core.py` (`build_context_panel`), `…/context/services.py` |
| SMART launch/callback + embedded session + context API | `apps/api/clinara/api_v1_embedded.py` |
| Embedded review surface (rendered in the EHR app frame) | `apps/api/clinara/embedded_surface.py`, `apps/api/clinara/templates/embedded.html` |
| Epic Showroom + Athena Marketplace manifests + deterministic validator | `clinical/marketplace/*.json`, `apps/api/domains/embedded/marketplace.py` |
| id_token verifier config (secrets/keys injected, never stored) | `clinara/settings/base.py` (`EHR_LAUNCH`) |
| Tests (launch flow + id_token validation; end-to-end bridge, isolation, expiry, panel, manifests) | `packages/integration-sdk/tests/test_smart_launch.py`, `apps/api/tests/test_phase8_embedded_surface.py` |

---

### Current status — Phase 9 (Billing & Coding Intelligence)

Phase 9 adds Elaborate's one missing revenue module — **coding optimization** — closing gap
**G1** in [`gaps.md`](./gaps.md): *"detects missing or under-coded diagnoses through patient
context analysis… improves documentation integrity and supports compliant risk capture."* It
rides on the exact same chart context the results pipeline already produced, and it holds the
architectural invariant that governs the whole platform — **governed clinical logic decides, no
model-driven clinical decision** — while carrying the extra compliance weight that coding demands
(upcoding is an audit exposure, so every suggestion must be deterministic, evidence-linked, and
human-confirmed).

The new `domains/coding` module analyses the canonical `ContextSnapshot` facts + documented
problem list + encounter diagnoses and flags three kinds of revenue-integrity gap **as
suggestions in an inert review queue, never applied to a claim**:

- **Documented-but-uncoded** — an active problem-list condition whose ICD-10 code is absent from
  the encounter's diagnoses.
- **HCC / risk-adjustment gap** — a risk-adjustable condition *suspected* from objective lab
  evidence at/over a diagnostic threshold (e.g. A1c ≥ 6.5% ⇒ suspected diabetes; eGFR < 60 ⇒
  suspected CKD stage 3+) yet neither documented nor coded. Always flagged
  `requires_provider_confirmation` — a suspected diagnosis is a prompt to the provider, never an
  assertion.
- **Specificity upgrade** — an unspecified code on the encounter the chart can sharpen (e.g.
  unspecified CKD `N18.9` + a staging eGFR → the specific stage; diabetes without complications
  `E11.9` + CKD evidence → diabetes *with* diabetic CKD).

The safety posture mirrors the Phase 6 governed loop and is enforced in code, not convention:

- **Deterministic + evidence-linked, or it does not exist.** The clinical content (ICD-10 codes,
  HCC tags, the KDIGO eGFR→CKD staging table, the ADA A1c threshold) is codified as *data* in
  `catalog.py` — the same way `MARKER_SPECS` codifies lab thresholds — so every suggestion is
  replayable. `core.analyze` **asserts** no suggestion is ever produced without concrete
  supporting evidence.
- **Conservative anti-upcoding thresholds.** Below the A1c diagnostic cut-off, or at eGFR ≥ 60,
  the module suggests **nothing** — it never reaches for the higher-weighted code (proven by
  negative unit tests).
- **Nothing auto-applies; a human is always in the loop.** Suggestions are created `PENDING`.
  Only `confirm_suggestion` / `reject_suggestion` (actor-attributed, audited, event-published)
  advance one, and `export_suggestion` releases **only** a `CONFIRMED` suggestion — a pending or
  rejected one can never be exported.
- **Governed, not a side metric.** Each confirm/reject is captured as `coding` feedback
  (approve/override) in the Phase 6 loop, so coding acceptance and override rates surface on the
  same governed dashboards as every other clinician action.

*Everything is pure and Django-free at the core (`core.py`, `catalog.py`), so the anti-upcoding
guardrails are exhaustively unit-tested (23 dedicated tests; full suite green — 153 passed). The
seed catalog covers the six Phase-1 markers' downstream conditions (diabetes, CKD); breadth
across specialties extends it through the same governed authoring path in Phase 10.*

| Phase 9 deliverable | Where |
|---|---|
| Deterministic clinical catalog (ICD-10, HCC tags, eGFR→CKD staging, A1c threshold) | `apps/api/domains/coding/catalog.py` |
| Pure gap detectors + `analyze` (documented-uncoded, HCC gap, specificity upgrade; evidence guardrail) | `apps/api/domains/coding/core.py` |
| Review-queue persistence (`CodingSuggestionRecord`, RLS-isolated, idempotent per gap) | `apps/api/domains/coding/models.py`, `…/migrations/0002_enable_rls.py` |
| Governed lifecycle (analyze / confirm / reject / export gate; audit + events; analytics hook) | `apps/api/domains/coding/services.py` |
| Rides the immutable snapshot the engine already reasoned over | `analyze_from_snapshot` → `apps/api/domains/context/models.py` |
| HTTP surface (`/api/v1/coding/analyze`, `/suggestions`, `/{id}/confirm|reject|export`) | `apps/api/clinara/api_v1_coding.py` |
| Acceptance/override fed into the Phase 6 governed dashboards | `apps/api/domains/analytics/services.py` (workflow-type loop) |
| Tests (each detector incl. negative cases, export gate, no-auto-apply, idempotency, tenant isolation, analytics hook) | `apps/api/tests/test_phase9_coding.py`, `apps/api/tests/test_api_coding.py` |

---

### Current status — Phase 10 (Specialty Protocol Breadth)

Phase 10 closes gap **G6** in [`gaps.md`](./gaps.md) — Elaborate's *"rules-based protocols
across 30+ ambulatory specialties."* It is a **content + governance** phase, delivered under the
platform invariant *no model-driven clinical decision*: the crown-jewel evaluator
(`clinara_protocol_engine`) is **not touched**. Breadth is data and governance, not new engine
code.

**The catalog grew from 6 markers to 25.** `packages/terminology/markers.py` now carries thyroid
(TSH, free T4), extended lipids (HDL, triglycerides, total cholesterol), a hepatic panel (ALT,
AST, bilirubin, alk phos), hematology (hemoglobin, platelets, WBC), coagulation (INR),
inflammatory (CRP, ESR), and electrolytes (sodium, calcium, BUN) — each with a canonical unit,
reference range, seed LOINC codes, and unit conversions. `LAB_FACT_ALIAS` is now **derived** from
the catalog (`MarkerSpec.fact_alias`), so **adding a marker is a pure data change** — the reason
the engine needs no edit to grow breadth. New conventional adult critical bands (sodium, calcium,
hemoglobin, platelets, WBC, INR) extend the un-weakenable safety floor.

**Seven parameterized protocol packs cover 34 ambulatory specialties.** Under
`clinical/protocols/specialties/`, each pack is versioned data: specialty-scoped, deterministic
rules whose thresholds are `{param: <name>}` placeholders with pack defaults, plus required
positive / negative / **critical-value** test cases. Their `scope.specialties` collectively cover
34 specialties — a *tested* coverage claim (`services.coverage_report()` → 34/34), not a marketing
one.

**Two guarantees, enforced in code (`domains/specialties`):**

- **Every pack passes the Rule Studio activation gate.** `core.validate_pack` binds every rule,
  asserts no rule down-classifies a critical value (`assert_cannot_weaken_safety`), and runs every
  required test case (`run_test_cases`) — the same gate `domains/protocols` enforces at deploy.
  Pack rules are authored bounded *above* the hard critical floor, so a critical value (Hgb < 6,
  INR > 5, Na < 120, …) escalates first and no pack rule can ever match it.
- **Per-tenant threshold customization with no code change — and it can never weaken safety.** A
  `SpecialtyThresholdPolicy` lets a practice retune a threshold; the override is *data* applied by
  `bind_parameters` at rule-load time (no rule YAML edited, no code shipped). `set_threshold`
  re-runs the **whole pack activation gate** with the proposed value before persisting, so an
  override that would down-classify a critical value, break a required test, or name an undeclared
  parameter is rejected (HTTP 422). `resolve_rules` composes the base rules with each pack bound to
  the tenant's effective thresholds — the exact, replayable rule set the engine evaluates, wired
  into `domains/workflows/services.py`.

*Proven end-to-end: the same TSH result yields a different governed decision for two practices
purely because one customized its threshold (`test_end_to_end_two_tenants_get_different_
classifications`, driven through the real ingest pipeline). 32 dedicated tests (23 domain/API + 9
catalog/critical); full suite green — 176 API + package tests passed. Authoring playbook:
[`docs/protocols/specialty-pack-authoring.md`](./docs/protocols/specialty-pack-authoring.md).*

| Phase 10 deliverable | Where |
|---|---|
| Catalog expansion (25 markers, fact-alias derivation, unit conversions) | `packages/terminology/markers.py`, `…/units.py` |
| New critical bands (Na, Ca, Hgb, Plt, WBC, INR) | `packages/protocol-engine/clinara_protocol_engine/critical.py` |
| 7 parameterized specialty protocol packs (34-specialty coverage) | `clinical/protocols/specialties/*.yaml` |
| Ambulatory specialty registry (34 specialties as data) | `apps/api/domains/specialties/catalog.py` |
| Pure pack mechanics (`bind_parameters`, `validate_pack`, `coverage`) | `apps/api/domains/specialties/core.py` |
| Governed per-tenant threshold policy + rule resolver | `apps/api/domains/specialties/services.py`, `…/models.py`, `…/migrations/0002_enable_rls.py` |
| Wired into the engine path (base rules + tenant-bound packs) | `apps/api/domains/workflows/services.py` |
| HTTP surface (`/api/v1/specialties`, `/packs`, `/packs/{key}/thresholds`) | `apps/api/clinara/api_v1_specialties.py` |
| Tests (pack gate, coverage, safety guard, per-tenant customization, tenant isolation, API) | `apps/api/tests/test_phase10_specialties.py`, `…/test_api_specialties.py`, `packages/**/test_phase10_*.py` |

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
