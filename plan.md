# Clinara HealthOS — Implementation Plan
### Phase-by-Phase Delivery Blueprint

**Companion to:** `CLINARA_HEALTHOS_REQUIREMENTS.md` (v1.0)
**Document type:** Engineering execution plan
**Audience:** Principal architect, engineering leads, clinical informatics, security, delivery
**Planning horizon:** Phase 0 → Phase 6 (+ GA hardening)

---

## 0. How to Read This Plan

This plan translates the requirements document into an executable sequence. It is opinionated where the spec leaves room, and it enforces the single most important architectural rule from the source document:

> **Generative AI may communicate and assist, but governed clinical logic decides.**

Every phase is written with the same anatomy so it can be lifted directly into a program board:

- **Objective** — the one-sentence purpose of the phase.
- **Why now (sequencing rationale)** — what this unblocks and what must precede it.
- **Workstreams** — parallelizable tracks with an owner archetype.
- **Deliverables** — concrete, demoable artifacts.
- **Key technical decisions** — the architectural choices to lock in during this phase.
- **Data model deltas** — the domain tables/aggregates introduced.
- **Interfaces & contracts** — APIs, events, and service boundaries added.
- **Testing focus** — what "done" is proven against.
- **Exit / acceptance gate** — binary criteria to advance.
- **Risks & mitigations** — phase-specific hazards.

A short **Cross-Cutting Foundations** section precedes the phases because several disciplines (safety, audit, tenancy, observability) are not phases — they are properties every phase must preserve.

---

## 1. Architectural North Star

### 1.1 The layered decision pipeline (non-negotiable shape)

Every clinical workflow, regardless of module, flows through the same governed pipeline. This is the backbone the whole program builds around:

```
Ingest → Normalize (canonical model) → Patient match → Build immutable context snapshot
   → Resolve effective configuration (hierarchy) → Evaluate deterministic protocol
   → [Deterministic decision produced] → LLM assists (summarize / draft / translate ONLY)
   → Output validation & safety gate → Human review (where required) → Deliver / write-back
   → Feedback capture → Analytics → Learning (governed, approval-gated)
```

Two hard invariants apply at every step:

1. **The clinical decision exists before the LLM is ever called.** The LLM never chooses classification, priority, thresholds, or actions. If the LLM is removed, the workflow still produces a safe, deterministic outcome.
2. **Nothing disappears silently.** Every inbound event is either processed, parked in a visible queue (dead-letter / unknown-code / no-match), or escalated — never dropped.

### 1.2 Deployment topology decision

- **Backend:** Modular monolith (Django + DRF + Pydantic) with strict module boundaries per the spec's `apps/` layout. Cross-module calls go through explicit service interfaces, never direct ORM reach-across. This preserves the option to extract services later without an early microservices tax.
- **Async spine:** Redis + Celery for standard event processing from day one. **Temporal** is introduced in Phase 3 for long-running, human-in-the-loop, durable workflows (scheduled follow-ups, multi-day refill flows). We do not force Temporal early — Celery covers Phases 0–2.
- **Event bus:** Domain events published to an append-only outbox table, relayed to SQS/EventBridge. The outbox pattern guarantees "zero silent loss" from the application boundary.
- **Frontend:** Next.js + React, SSR for admin/authoring surfaces, with an accessibility-first component library and role-based navigation. EHR-embeddable clinician surface (SMART on FHIR launch) is designed for in Phase 1, delivered in Phase 3.
- **Tenancy:** Single database, tenant-scoped rows with PostgreSQL Row-Level Security (RLS) enforced at the connection/session level. Tenant isolation is a Phase 0 deliverable and is regression-tested every subsequent phase.

### 1.3 Repository shape (established Phase 0)

Adopt the spec's Section 20 structure. The `packages/protocol-engine`, `packages/clinical-models`, and `packages/terminology` packages are the crown-jewel assets and get the strictest review, versioning, and test coverage.

---

## 2. Cross-Cutting Foundations (present in every phase)

These are not scheduled phases; they are acceptance dimensions checked at every gate.

| Discipline | Standing requirement enforced at every phase gate |
|---|---|
| **Safety layering** | The 12 safety layers (spec §11.1) relevant to the phase's surface area are implemented and tested. Safety constraints are never weakened by lower-precedence config. |
| **Auditability** | Every state-changing action emits an immutable audit record with actor/action/resource/tenant/before/after/reason/correlation-id (spec §10.4). Target: 99.9% audit-write success. |
| **Tenant isolation** | RLS + authorization tests run in CI. A cross-tenant read/write attempt is a release-blocking failure. |
| **Explainability** | Every decision produces a complete, replayable decision trace referencing exact facts and rule versions used. |
| **Observability** | New surfaces ship with metrics, structured PHI-safe logs, traces (OpenTelemetry), and alerts wired before the feature is "done." |
| **Idempotency** | Any new inbound path derives a stable idempotency key (spec §6.7.6); duplicates never double-communicate or double-task. |
| **Reversibility** | Any deployable clinical artifact (rule, mapping, config) has a tested rollback path. |
| **PHI-safe logging** | No PHI in logs/metrics/traces. Enforced by a logging middleware + CI lint. |

---

## 3. Program Sequencing & Critical Path

```
Phase 0  Foundation ─────────────┐
                                  ▼
Phase 1  Results Intelligence MVP ───────────► (proves the whole pipeline end-to-end)
                                  │
                    ┌─────────────┴─────────────┐
                    ▼                            ▼
Phase 2  Clinical Rule Studio        Phase 3  Production EHR Integration
   (lets clinicians own logic)          (makes it real-world durable)
                    │                            │
                    └─────────────┬──────────────┘
                                  ▼
Phase 4  Prescription Intelligence  (second workflow on proven rails)
                                  ▼
Phase 5  Patient Message Intelligence (adds LLM classification under deterministic red-flag guard)
                                  ▼
Phase 6  Analytics & Personalization (closes the feedback loop, governed learning)
                                  ▼
       GA Hardening (compliance attestation, DR drills, scale)
```

**Critical path:** Phase 0 → 1 → (2 ∥ 3) → 4 → 5 → 6.
Phase 2 and Phase 3 can run largely in parallel with distinct teams once Phase 1 stabilizes the canonical model and the protocol-engine interface. Phase 4 depends on **both** (needs Rule Studio for refill protocols and production integration for medication data). Phase 5 depends on Phase 3 (patient-portal messaging channel). Phase 6 depends on accumulated feedback data from Phases 1, 4, 5.

---

# Phase 0 — Foundation

**Objective:** Stand up a tenant-isolated, auditable, observable platform skeleton that every clinical capability will later plug into — with zero clinical logic yet.

**Why now:** Nothing clinical can be trusted before tenancy, identity, audit, and the canonical event contract are immovable. Building these first prevents retrofitting isolation and audit into live clinical code — the most expensive class of rework in healthcare software.

### Workstreams

1. **Platform & Infra** (Platform engineer) — Terraform baseline: VPC with private subnets, RDS PostgreSQL (Multi-AZ), ElastiCache Redis, S3 (versioned), SQS, EventBridge, Secrets Manager, KMS, CloudTrail, WAF. ECS/EKS cluster. GitHub Actions CI/CD with signed, immutable container artifacts and vulnerability scanning.
2. **Identity, Tenancy & RBAC** (Backend) — Organization → Site → Department → Practice → Specialty → CareTeam → Practitioner/User hierarchy. OIDC/SAML SSO, MFA, RBAC with the 11 roles from spec §10.2, least-privilege defaults, break-glass and just-in-time privileged access scaffolding.
3. **Audit Framework** (Backend + Security) — Append-only `AuditEvent` store with the mandatory field set; audit is a service interface, not scattered logging. Tamper-evident (hash-chained) records.
4. **Canonical Contracts** (Architect) — Freeze the canonical clinical event schema (spec §8.2), the domain event envelope (immutable, versioned, tenant-aware, correlation + causation + idempotency ids), and the transactional **outbox** pattern.
5. **Observability Baseline** (Platform) — OpenTelemetry tracing, Datadog/CloudWatch metrics, Sentry, structured PHI-safe logging middleware, the base SLO dashboards.

### Deliverables

- Reproducible infra from `terraform apply` across Local/Dev environments.
- Working SSO login → role-scoped session → every request tenant-scoped via RLS.
- Audit records generated for auth + config changes, queryable by compliance role.
- Canonical event schema + event envelope published as a versioned package (`packages/shared-types`, `packages/clinical-models`).
- CI pipeline: lint, type-check, unit tests, container build/scan/sign, migration validation, PHI-safe-log lint.
- "Hello, tenant" reference workflow proving an event flows through the outbox → bus → a no-op worker with full trace + audit.

### Key technical decisions

- **RLS over app-layer filtering** for tenant isolation — defense in depth; app bugs cannot leak across tenants.
- **Outbox + relay** over direct publish — guarantees at-least-once, no silent loss.
- **Pydantic models as the canonical contract layer** shared between ingestion and workers; Django ORM models are persistence, not contracts.

### Data model deltas

Tenancy domain (all of spec §8.1 Tenancy), Integration stubs, `AuditEvent`, `DomainEventOutbox`, `Deployment`/`Rollback` scaffolding.

### Testing focus

Tenant-isolation authorization suite (the permanent regression harness), audit-completeness tests, infra reproducibility, DR backup/restore smoke.

### Exit / acceptance gate

- [ ] Tenant-isolated platform operational; cross-tenant access test suite green.
- [ ] Audit records generated and immutable for all implemented actions.
- [ ] Infrastructure reproducible from code in a clean account.
- [ ] Production-mode logging verified PHI-safe by automated scan.
- [ ] Canonical event schema versioned and consumed by a reference worker.

### Risks & mitigations

- *Isolation gaps discovered late* → make the cross-tenant test suite a permanent, ever-growing CI gate from day one.
- *Audit as afterthought* → audit is a required interface every mutating service must call; enforced by architecture review + a lint that flags mutations without an audit emit.

---

# Phase 1 — Results Intelligence MVP

**Objective:** Prove the **entire** governed pipeline end-to-end for laboratory results, in a sandbox, with human approval required for every patient-facing output.

**Why now:** Results Intelligence is the narrowest, most deterministic workflow — ideal to validate the pipeline shape (§1.1) before generalizing. It exercises ingestion, canonicalization, context, deterministic rules, LLM-assisted drafting, validation, human review, and decision trace in one thin vertical slice. This phase *is* the MVP acceptance surface (spec §19).

### Workstreams

1. **FHIR Ingestion (sandbox)** (Integration) — SMART-on-FHIR backend-services auth; ingest `Observation` / `DiagnosticReport` + supporting `Patient`, `Encounter`, `Condition`, `MedicationRequest`. Raw payload stored before parsing; idempotency key derived.
2. **Terminology & Mapping (seed)** (Data/Clinical) — Seed LOINC → canonical marker map for the initial marker set. Unit normalization via UCUM with deterministic, tested conversions. Unsupported unit → **block interpretation** (safety rule). Unknown code → unknown-code queue.
3. **Canonical Data Layer** (Backend) — Transform vendor payloads into the canonical clinical model; compute historical comparisons (prior value, trend) from stored canonical events.
4. **Context Builder** (Backend) — Produce the immutable `ContextSnapshot` (spec §8.3) recording source ids, timestamps, freshness, missing facts, conflicting facts, transformations, mappings, and builder version.
5. **Deterministic Protocol Engine v1** (Architect + Backend) — The crown jewel. Evaluate versioned rules (YAML per spec §6.5.3) against a context snapshot; produce the structured result output (spec §6.1.5) with classification, priority, recommended action, reason codes, and `clinical_facts_used`. Hard-coded critical thresholds that **cannot** be weakened.
6. **Communication Generation (constrained)** (AI engineer) — LLM drafts patient message + clinician summary from **approved templates + structured facts only**. Model may summarize/simplify/rewrite tone; may not choose thresholds, diagnose, invent facts, or weaken warnings (spec §6.9.4).
7. **Output Validation & Safety Gate** (Backend + Clinical) — Schema, fact consistency, numeric consistency, required-warning, prohibited-claim, PHI-boundary, template-compliance, and hallucination checks (spec §6.9.5). Failure → deterministic fixed-template fallback + route to human (spec §6.9.6).
8. **Clinician Review UI** (Frontend) — Inbox item with priority, summary, chart facts, trend, recommended action, message preview, reason codes, automation status, and Approve/Edit/Override/Escalate/Close/View-reasoning/View-source controls (spec §6.10.1).
9. **Decision Trace & Replay** (Backend) — Full trace from inputs to output; workflow replay from stored canonical event + snapshot.

### Deliverables

- End-to-end sandbox flow: FHIR result in → canonical → context → protocol decision → validated draft → clinician approves/edits/rejects → audited.
- At least **five** core markers fully supported (A1C, glucose, creatinine/eGFR, potassium, LDL recommended for clinical breadth).
- The result classification taxonomy (spec §6.1.4) implemented, including Unsupported / Insufficient data / Conflicting data.
- Operations queue surfacing failed and unmapped events.
- Rule authored **as versioned YAML in the repo** (Studio comes in Phase 2 — here rules are code-reviewed artifacts, not app logic).

### Key technical decisions

- **Rules are data, not code** — even in Phase 1, protocols live as versioned declarative artifacts evaluated by the engine, so Phase 2's Studio has a target format from the start.
- **Context snapshot is immutable and hashed** — replay and audit reproduce the exact evaluation inputs.
- **Two-stage safety on criticals** — critical thresholds are evaluated deterministically and bypass normal queues; automation is suppressed when required context is missing.
- **LLM is a pure function of (approved template + structured facts)** — no chart free-text is passed as authority; this contains hallucination and PHI exposure.

### Data model deltas

Clinical Data domain (`PatientReference`, `Observation`, `DiagnosticReport`, `Condition`, `MedicationRequest`, …), Workflow domain (`WorkflowInstance`, `ContextSnapshot`, `ProtocolEvaluation`, `ClinicalDecision`, `GeneratedCommunication`, `HumanReview`, `Escalation`, `Outcome`), Clinical Logic seed (`Protocol`, `ProtocolVersion`, `Rule*`, `SafetyConstraint`, `CommunicationTemplate`), Terminology (`IntegrationMapping`, `MappingProposal`).

### Interfaces & contracts

- Events: `ObservationReceived`, `DiagnosticReportReceived`, `ContextBuilt`, `ProtocolEvaluated`, `DecisionCreated`, `CommunicationGenerated`, `CommunicationValidated`, `ClinicianApproved/Edited/Overrode`, `WorkflowEscalated`.
- APIs: `GET/POST /api/v1/workflows`, `/workflows/{id}/approve|edit|override|escalate|replay`.

### Testing focus

Clinical rule tests (positive/negative/boundary/missing/conflicting/high-risk cohort/unit-variant per spec §13.2); the seed **golden dataset** (spec §13.3); LLM evals for factual/numeric/medication consistency, omitted warnings, reading level (spec §13.4); critical-value-cannot-auto-resolve tests; replay determinism.

### Exit / acceptance gate (this is the MVP gate — maps to spec §19)

- [ ] Lab result received via FHIR → normalized to canonical marker.
- [ ] Relevant patient context retrieved into an immutable snapshot.
- [ ] Versioned deterministic protocol evaluated; output has classification, priority, recommended action, reason codes.
- [ ] Patient-friendly message generated from approved inputs and passes validation.
- [ ] Clinician can approve / edit / reject; every action audited.
- [ ] Workflow replayable; failed events appear in the operations queue.
- [ ] Tenant isolation validated; **critical values cannot be auto-resolved**.
- [ ] No automated patient delivery without approval; no inbound event lost silently.

### Risks & mitigations

- *Overreach into automation* → Phase 1 delivery is explicitly "human approval required" mode only; auto-delivery is architecturally disabled.
- *LLM contaminating decisions* → validation gate rejects any output whose facts/numbers diverge from the deterministic decision; fixed-template fallback guarantees a safe path.
- *Terminology drift* → unsupported units and unknown codes block interpretation rather than guessing.

---

# Phase 2 — Clinical Rule Studio

**Objective:** Let clinical experts author, simulate, test, approve, deploy, and roll back clinical logic **without any application code change**.

**Why now:** Phase 1 proved the engine consumes declarative rules. Phase 2 puts a governed authoring surface on top so clinical velocity is decoupled from engineering releases — the core business differentiator (spec §21).

### Workstreams

1. **Visual Rule Builder** (Frontend + Backend) — Structured condition editor with nested Boolean logic, type-safe operators, a data dictionary of available facts, reusable predicates and action groups, evidence references, template association, and a scope selector (spec §6.5.5). Inline validation and conflict warnings.
2. **Simulation Engine** (Backend) — Run a proposed rule version against synthetic scenarios or de-identified historical cases under a chosen tenant/clinician context; compare current vs proposed behavior; inspect matched/rejected rules, facts used, missing facts; preview patient + clinician communication (spec §6.5.6).
3. **Impact Analysis** (Backend + Data) — Before activation, report tenants/specialties/clinicians affected, historical behavior changes, conflicting rules, overridden customizations, missing data dependencies, automation-rate and escalation-rate deltas, and high-risk-cohort impact (spec §6.5.7).
4. **Versioning, Approval & Lifecycle** (Backend) — Rule state machine: Draft → In review → Approved → Scheduled → Active → Deprecated → Retired → Rolled back (spec §6.5.4). Dual approval (clinical + engineering where required). Version comparison / diff.
5. **Deployment & Rollout** (Backend) — Scheduled release, percentage/tenant/site/specialty/clinician-cohort rollout, **shadow mode**, automatic rollback conditions, manual rollback, deployment audit (spec §6.5.8). Clinical config deploys **separately from app code** (spec §14.3).
6. **Conflict Detection** (Architect) — Detect precedence conflicts across the configuration hierarchy; conflicting configurations **suppress automation** rather than resolving ambiguously (spec §6.4.3).

### Deliverables

- A clinical programmer authors a rule in the UI, simulates it against historical cases, sees an impact report, routes for approval, deploys to a tenant subset in shadow mode, promotes, and rolls back — with no engineering involvement.
- Config-release bundle artifact (versioned, with approval record, impact report, test results, effective date, target scope, rollout plan, rollback version, monitoring plan).
- Regression-test enforcement: a rule cannot activate if its required test cases fail.

### Key technical decisions

- **Rules are versioned, content-addressed bundles** deployed through a pipeline distinct from application CI/CD — clinical change cadence ≠ code change cadence.
- **Shadow mode is a first-class automation mode** (spec §11.2), evaluating new logic against live traffic without acting, capturing agreement deltas before promotion.
- **Conflict → suppression, never silent resolution** — ambiguity always degrades to human review.

### Data model deltas

`ProtocolScope`, `ProtocolOverride`, rule test-case entities, `Deployment`, `Rollback`, config-bundle metadata; simulation run records (de-identified).

### Interfaces & contracts

- APIs: `/api/v1/protocols` CRUD, `/{id}/versions`, `/{id}/simulate`, `/{id}/approve`, `/{id}/deploy`, `/{id}/rollback`.
- Events: `ProtocolDeployed`, plus simulation/impact events.

### Testing focus

Simulation fidelity (simulated vs actual evaluation parity), impact-analysis accuracy against historical data, rollback correctness, conflict-detection completeness, dual-approval enforcement, config-vs-code deployment isolation.

### Exit / acceptance gate

- [ ] A clinical programmer creates and deploys an approved rule with **no code change**.
- [ ] Impact analysis available and accurate before activation.
- [ ] Regression testing enforced as an activation gate.
- [ ] Shadow mode, progressive rollout, and rollback all demonstrated.
- [ ] Configuration conflicts detected and shown to suppress automation.

### Risks & mitigations

- *Authors bypassing safety* → global safety constraints are engine-enforced and not editable in the Studio; the builder physically cannot weaken them.
- *Bad rule reaching production* → mandatory simulation + impact + approval + shadow + progressive rollout + auto-rollback layered defense.

---

# Phase 3 — Production EHR Integration

**Objective:** Turn the sandbox pipeline into a production-grade, always-on integration surface with real HL7/FHIR ingestion, write-back, patient-portal messaging, and zero silent failures.

**Why now:** Runs in parallel with Phase 2 (different team). Phase 1 validated the logical pipeline; Phase 3 makes it survive real-world message chaos, retries, duplicates, and interface outages — prerequisites for any customer deployment and for Phases 4–5 which need production channels.

### Workstreams

1. **Integration Gateway (hardened)** (Integration) — Authenticate inbound, resolve tenant, validate payload, store raw, generate idempotency key, detect duplicates, normalize timestamps, publish canonical events, ack/reject, record latency, dead-letter failures, rate-limit abusive sources, guard against malformed payloads (spec §6.7.4).
2. **HL7 v2 Adapter** (Integration) — MLLP listener; ADT / ORU / ORM / MDM message types → canonical model via the adapter architecture (integration logic never leaks into protocol logic).
3. **FHIR Production Connection** (Integration) — Production SMART-on-FHIR, backend service authorization, full initial resource set (spec §6.7.3).
4. **EHR Write-Back & Delivery Service** (Integration) — Task/inbox write-back APIs, patient-portal messaging APIs; delivery confirmation; `DeliverySucceeded/Failed` events.
5. **Durable Workflow Orchestration** (Architect) — Introduce **Temporal** for long-running flows: human-review pauses, scheduled follow-up, timeouts, compensation, reprocessing, versioned workflows (spec §7.6).
6. **Operations Tooling** (Backend + Frontend) — Integration health dashboard (per-interface connection status, throughput, error/latency/queue/duplicate/unknown-code/patient-match-failure/write-back-failure/retry/dead-letter counts — spec §6.7.5), dead-letter management UI, message replay, synthetic event generation.
7. **EHR-Embedded Clinician Surface** (Frontend) — SMART-on-FHIR launch so the clinician view embeds in the EHR (spec §6.10.2) — no separate workflow where embedding is possible.

### Deliverables

- Production interface monitoring with alerting on the critical set (interface disconnected, critical event delayed, silent event gap, write-back spike — spec §12.3).
- Dead-letter queue with inspect/replay; reprocessing proven idempotent.
- Tenant-specific mappings supported at the gateway.
- EHR write-back of tasks/messages confirmed against a sandbox EHR.

### Key technical decisions

- **Adapter-per-source, canonical-in-the-middle** — vendor quirks are isolated in adapters; the protocol engine only ever sees canonical events.
- **Temporal for durable, human-in-loop workflows; Celery/SQS for stateless event processing** — right tool per workload, not one-size-fits-all.
- **Silent-gap detection** — heartbeat/sequence monitoring per interface detects *absence* of expected traffic, not just failures of received traffic.

### Data model deltas

Full Integration domain (`Integration`, `IntegrationEndpoint`, `IntegrationCredential`, `InboundMessage`, `OutboundMessage`, `DeliveryAttempt`, `DeadLetterEvent`), `IntegrationError`, `Alert`, `Incident`.

### Interfaces & contracts

- APIs: `/api/v1/integrations` CRUD, `/{id}/health`, `/{id}/errors`, `/{id}/test`, `/{id}/replay`.
- Events: `PatientUpdated`, `EncounterUpdated`, `DeliverySucceeded`, `DeliveryFailed`, `MappingChanged`.

### Testing focus

EHR-simulator tests, contract tests per interface, chaos tests (interface flap, duplicate storms, malformed payloads), replay/reprocessing idempotency, silent-gap detection, write-back failure handling.

### Exit / acceptance gate

- [ ] Production-grade interface monitoring live with critical alerts.
- [ ] **Zero silent failures** demonstrated under chaos testing.
- [ ] Reprocessing/replay tested and idempotent.
- [ ] Tenant-specific mappings supported.
- [ ] Duplicate events never produce duplicate communication or tasks.

### Risks & mitigations

- *Integration fragility* → canonical model + adapters + dead-letter + replay + contract tests (spec §18).
- *Silent event loss* → outbox + per-interface sequence/heartbeat monitoring + SLO alert on gaps.

---

# Phase 4 — Prescription & Refill Intelligence

**Objective:** Deliver the second clinical workflow — refill evaluation — on the proven rails, reducing chart-review effort while enforcing deterministic medication safety.

**Why now:** Depends on **both** Phase 2 (refill protocols authored in Studio) and Phase 3 (production medication data + write-back). Refills are higher-risk than results (controlled substances, contraindications), so they follow only after the authoring and integration disciplines are mature.

### Workstreams

1. **Refill Ingestion** (Integration) — Refill request events from EHR channels into the canonical model.
2. **Medication Normalization** (Terminology) — RxNorm mapping; medication identity resolution; **missing identity blocks automation** (safety).
3. **Refill Protocol Engine** (Backend) — Evaluate the full factor set (spec §6.3.2: active status, dose match, refill timing, class, controlled status, diagnosis, last visit, monitoring labs, vitals, allergies, contraindications, interactions, pregnancy/renal/hepatic status, discontinuation, client policy, clinician preference). Produce the refill decision output (spec §6.3.4) with decision, reason codes, required actions, and the exact context used.
4. **Deterministic Safety Checks** (Clinical + Backend) — Allergy/contraindication/interaction evaluation is **deterministic, never LLM** (spec §6.3.5). Monitoring requirements are client-configurable. Dose mismatch → manual review. Controlled substances → separate policy path.
5. **Routing & Outcomes** (Backend) — The full outcome set (spec §6.3.3): auto-approve (only explicitly approved low-risk), one-click prep, route to nurse/prescriber, request labs/appointment, reject (too early / discontinued), escalate (contraindication / missing data / controlled-substance policy).
6. **Human Approval Surface** (Frontend) — Refill review with one-click approval where eligible; controlled-substance flows always human.

### Deliverables

- Approved medication classes supported end-to-end.
- Every refill decision logs the exact data used (spec §6.3.5).
- Safety exclusions (missing identity, dose mismatch, controlled substances, contraindications) enforced and tested.

### Key technical decisions

- **Medication changes are never LLM-generated** — the LLM only drafts the *response wording* around a deterministic decision.
- **Controlled-substance policy is a separate, non-overridable constraint layer** — client/clinician config cannot loosen it.

### Data model deltas

`Medication`, `MedicationStatement`, `AllergyIntolerance`, refill-specific decision/outcome records; client monitoring-requirement config.

### Testing focus

Contraindication/interaction determinism, monitoring-lab-overdue logic, dose-mismatch and discontinuation handling, controlled-substance policy enforcement, high-risk cohort exclusions.

### Exit / acceptance gate

- [ ] Approved medication classes supported.
- [ ] All refill decisions traceable to exact data used.
- [ ] Safety exclusions enforced (identity, dose, controlled substances, contraindications).
- [ ] No medication change ever produced by an LLM.

### Risks & mitigations

- *Unsafe auto-approval* → auto-approve is gated to an explicitly approved low-risk allowlist with deterministic safety preconditions; everything else routes to a human.

---

# Phase 5 — Patient Message Intelligence

**Objective:** Classify, extract, summarize, prioritize, and route inbound patient messages — with LLM classification always subordinate to deterministic emergency detection.

**Why now:** The most LLM-dependent module, deliberately last among clinical workflows so the deterministic safety scaffolding, validation gate, and human-review patterns are battle-tested. Requires Phase 3's patient-portal channel.

### Workstreams

1. **Message Ingestion & Language Detection** (Integration + AI) — Ingest from supported EHR channels; preserve the original message verbatim; detect language for multilingual handling.
2. **Deterministic Red-Flag Detection** (Clinical + Backend) — **Rule-based** emergency/red-flag detection runs **in addition to** model classification (spec §6.2.6). Emergencies escalate immediately. The system must never falsely reassure when red flags are present.
3. **LLM Classification & Extraction** (AI) — Category (spec §6.2.2), symptoms/medications/duration/severity/requested-action extraction, structured summary (spec §6.2.5). **Model confidence alone never determines urgency.**
4. **Urgency Assignment** (Backend) — Deterministic urgency mapping (spec §6.2.4) combining red-flag rules + classification, never model confidence alone.
5. **Context & Patient-Identity Validation** (Backend) — Validate patient identity and encounter context before any chart-based reasoning; **detect and prevent cross-patient context contamination** (spec §6.2.6).
6. **Routing, Follow-up Questions & Draft Response** (Backend + AI) — Route to clinician/nurse/pool/admin; ask *approved* follow-up questions when info is missing; draft responses; automate only approved non-clinical/low-risk responses. High-risk categories are never fully auto-resolved.

### Deliverables

- Emergency messages escalated via deterministic rules regardless of model output.
- Classification performance meeting the agreed clinical threshold on the golden dataset.
- Multilingual summary + response drafting through the validation gate.
- No high-risk category auto-resolved.

### Key technical decisions

- **Two-channel urgency**: deterministic red-flag detector is the safety floor; the LLM can only *raise* concern, never *lower* it below the deterministic result.
- **Cross-patient contamination guard** as an explicit validation layer before chart reasoning.

### Data model deltas

Patient `Communication` (inbound), message classification/extraction records, red-flag evaluation records, routing decisions.

### Testing focus

Red-flag detection recall (missed-escalation = release blocker), false-reassurance suppression, cross-patient contamination tests, classification accuracy vs threshold, prompt-injection resistance, multilingual consistency (spec §13.4).

### Exit / acceptance gate

- [ ] Emergency messages escalated (deterministic rules verified independent of model).
- [ ] Classification performance meets the clinical threshold.
- [ ] No high-risk autonomous resolution.
- [ ] Cross-patient context contamination prevented.

### Risks & mitigations

- *LLM under-triage / false reassurance* → deterministic red-flag floor + validation gate + human review for anything above informational/administrative.
- *Prompt injection via patient text* → input sanitization, PHI-safe prompt construction, output validation, and never granting the model authority over routing/urgency.

---

# Phase 6 — Analytics & Personalization

**Objective:** Close the loop — turn accumulated clinician feedback into governed analytics and *approval-gated* personalization that never weakens safety.

**Why now:** Requires a meaningful volume of decisions, edits, overrides, and outcomes from Phases 1/4/5. Personalization is last because it is only trustworthy once the deterministic base and feedback capture are proven.

### Workstreams

1. **Feedback Domain** (Backend) — `ClinicianApproval/Edit/Override`, `PatientResponse`, `ProtocolFeedback`, edit-difference analysis (what clinicians change and why).
2. **Analytics Dashboards** (Data + Frontend) — Executive, Clinical, and Operations dashboards (spec §12) across all analytics dimensions (tenant/site/department/specialty/clinician/workflow/protocol/cohort/time/source/automation-mode).
3. **Clinician Preference Profiles** (Data) — Derive preference signals from edit/override patterns — wording, follow-up cadence, permitted low-risk behavior — **within** the constraint that preferences may never weaken global or client safety (spec §6.4.3).
4. **Governed Configuration Recommendations** (Data + Clinical) — The system *recommends* config changes; recommendations **require human approval** and flow through the Phase 2 deployment pipeline. No autonomous self-modification.
5. **Privacy Controls** (Security) — Minimum-necessary reporting, aggregation thresholds, role-based access, export controls, de-identification for any cross-tenant analysis (spec §12.5).

### Deliverables

- Clinical agreement / edit / override / escalation analytics live.
- Clinician preference profiles feeding *suggested* (not auto-applied) personalization.
- Configuration recommendations requiring approval before deployment.
- Cross-tenant privacy controls validated.

### Key technical decisions

- **Personalization is a recommendation engine, not an actuator** — every change routes back through governed deployment.
- **De-identification is mandatory for any cross-tenant learning** — no model training on identifiable customer data without explicit authorization (spec §4.2).

### Data model deltas

Full Feedback domain, `ConfigurationRecommendation`, `PractitionerPreference`, analytics aggregates.

### Testing focus

Analytics correctness, aggregation-threshold enforcement, cross-tenant de-identification, approval-gating of recommendations, preference-never-weakens-safety invariant.

### Exit / acceptance gate

- [ ] Personalization remains fully auditable.
- [ ] Recommendations require approval before taking effect.
- [ ] Cross-tenant privacy controls validated.
- [ ] Preference profiles provably cannot weaken safety constraints.

### Risks & mitigations

- *Personalization drifting toward unsafe autonomy* → recommendations are inert until approved and deployed through the governed pipeline; safety constraints are precedence-protected.

---

# GA Hardening (post-Phase 6, pre-general-availability)

**Objective:** Convert a feature-complete platform into a compliant, resilient, at-scale product.

### Focus areas

- **Compliance attestation** — HIPAA / SOC 2 Type II evidence collection, HITECH, BAAs, data-lineage and access-log completeness for auditors (spec §10.1, §5.8).
- **Disaster recovery drills** — Multi-AZ verified, PITR, quarterly restore tests, integration replay + workflow reconciliation, manual-operations fallback. Targets: RTO 4h core / RPO 15min transactional (spec §15).
- **Security hardening** — Penetration testing, LLM kill-switch validation across all scopes (spec §11.4), provider failover, break-glass audit.
- **Scale & performance** — Meet SLOs: 99.9% ingestion availability, 99% routine < 2min, 99% critical < 30s, 100% decision-trace availability (spec §12.4).
- **Release-gate enforcement** — The full §13.5 gate set wired into CI/CD as blocking checks.

### Exit / acceptance gate

- [ ] SOC 2 Type II readiness confirmed; audit evidence automated.
- [ ] DR restore test passes within RTO/RPO.
- [ ] All SLOs met under load.
- [ ] Every release-gate condition (spec §13.5) enforced automatically.

---

## 4. Testing Strategy Across Phases

Testing is layered so that each phase adds its slice without regressing prior guarantees.

| Test type | Introduced | Runs thereafter |
|---|---|---|
| Unit / domain | Phase 0 | Every phase |
| Tenant-isolation authorization | Phase 0 | Every phase (blocking) |
| Audit-completeness | Phase 0 | Every phase |
| Clinical rule tests (§13.2) | Phase 1 | Every clinical phase |
| Golden dataset (§13.3) | Phase 1 | Grows each phase |
| LLM evaluations (§13.4) | Phase 1 | Every phase touching generation |
| Simulation / impact fidelity | Phase 2 | Rule changes |
| Contract / EHR-simulator | Phase 3 | Every integration change |
| Chaos / silent-gap | Phase 3 | Ongoing |
| Prompt-injection / contamination | Phase 5 | Ongoing |
| Privacy / de-identification | Phase 6 | Ongoing |
| DR / performance / security | GA | Scheduled (quarterly DR) |

**Universal release gate (spec §13.5):** no release proceeds if critical regression, safety rules, mapping validation, or cross-tenant isolation tests fail; if required clinical approval is missing; if historical high-risk cases change unexpectedly; if observability is incomplete; or if rollback is unavailable.

---

## 5. Team & Ownership Map

| Workstream family | Primary owner archetype (spec §17) |
|---|---|
| Infra, CI/CD, observability | Platform engineer |
| Tenancy, identity, audit, protocol engine | Principal architect + Backend |
| Canonical model, context builder, terminology | Backend + Data engineer |
| HL7/FHIR adapters, gateway, write-back | Integration engineer |
| LLM generation, classification, evals | ML / applied AI engineer |
| Clinician & authoring UIs | Frontend engineer |
| Rule authoring, simulation, clinical test cases | Clinical informaticist + Clinical programmers |
| Safety constraints, medication safety | Medical director + Medication safety reviewer |
| Security, compliance, privacy | Security engineer + Compliance lead |
| Quality, regression, golden dataset | QA / test automation engineer |

---

## 6. Guiding Constraints Restated (the plan's guardrails)

Every phase decision is checked against the ten non-negotiable design principles (spec §2.4). The three that most shape sequencing:

1. **Patient safety over automation rate** — we ship narrow, high-agreement workflows before broad ones (spec §21).
2. **Governed logic decides; AI assists** — the deterministic decision always precedes and constrains generation.
3. **Nothing silent** — outbox, dead-letter, unknown-code queues, and gap detection are foundational, not features.

> A low-risk workflow with 98% clinical agreement is more valuable than a broad workflow with unpredictable behavior. The plan optimizes for correctness, auditability, integration reliability, and clinician trust — in that order — before automation volume.
