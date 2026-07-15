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
| **Phase 2** | **Clinical Rule Studio** — author/simulate/deploy/roll-back clinical logic with no code change. | ⬜ Planned |
| **Phase 3** | **Production EHR Integration** — hardened HL7/FHIR ingestion, write-back, zero silent failures. | ⬜ Planned |
| **Phase 4** | **Prescription & Refill Intelligence** — second workflow on proven rails. | ⬜ Planned |
| **Phase 5** | **Patient Message Intelligence** — LLM classification under a deterministic red-flag floor. | ⬜ Planned |
| **Phase 6** | **Analytics & Personalization** — governed, approval-gated learning loop. | ⬜ Planned |
| **GA** | Compliance attestation (HIPAA / SOC 2 Type II), DR drills, scale & performance SLOs. | ⬜ Planned |

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

Run the tests: `cd apps/api && pytest` (workflow + API + app-layer isolation on SQLite);
`PYTHONPATH=apps/api pytest packages tests/unit tests/clinical-regression` (the deterministic
clinical core + golden dataset). PostgreSQL RLS is verified by the `rls` CI job.

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
