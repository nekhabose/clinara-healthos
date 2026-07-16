# Clinara HealthOS — Gap Analysis & Closure Plan
### Feature parity vs. Elaborate (elaborate.com), and the phased plan to reach it

**Author's note (2026-07-15):** This document benchmarks the current implementation
(Phases 0–6 + GA Hardening + Phase 7 Real EMR Connectivity + Phase 8 EHR-Embedded Surface +
Phase 9 Billing & Coding Intelligence + Phase 10 Specialty Protocol Breadth +
Phase 11 Data Lifecycle & Compliance Hardening, all landed)
against **Elaborate** — the product Clinara is a replica of — identifies every remaining gap,
and lays out a phase-by-phase plan to close them. It is a companion to [`plan.md`](plan.md) and
continues its phase numbering. **With Phase 11 landed, every identified gap (G1–G7) is closed.**
Read `plan.md` first for the architectural north star; this document assumes it.

---

## 0. How to read this document

- **§1** states the one architectural invariant a faithful replica must preserve.
- **§2** is the parity scorecard — every Elaborate capability and where Clinara stands.
- **§3** describes each open gap in detail (what Elaborate does, current state with file
  references, what's missing, risk).
- **§4** is the phased closure plan (Phases 7–11), each with objective, workstreams,
  deliverables, and an exit/acceptance gate in the same shape as `plan.md`.
- Status legend: ✅ at/above parity · ⚠️ partial (interface exists, real work stubbed) ·
  ❌ missing.

---

## 1. The invariant to preserve (do not break during closure)

Elaborate is **not a generative-AI agent platform**. It is a **deterministic, auditable,
protocol-based** system, by explicit design:

> "No black boxes and no hallucinations — just clear, repeatable logic you can count on.
> The foundation of our system is deterministic and auditable." — elaborate.com/technology

Their "Protocol Automation / Protocol Intelligence Technology" is: evidence-based
guidelines (e.g. UpToDate) → in-house clinical validation against real charts → codified
into deterministic decision logic → per-practice threshold customization → refined via
acceptance/override feedback. Design pillars: **Predictable, Testable, Traceable.**

This is **exactly** Clinara's existing architecture (`plan.md §1`: *"Generative AI may
communicate and assist, but governed clinical logic decides"*). **Every gap below must be
closed without introducing model-driven clinical decisions.** Any LLM remains subordinate:
wording/tone/translation only, behind the Phase 1 validation gate. The gaps are integration
surface, a missing revenue module, compliance lifecycle, and protocol-content breadth — not
an architectural redirection.

---

## 2. Parity scorecard

| # | Elaborate capability | Clinara status | Evidence / where |
|---|---|---|---|
| — | Deterministic protocol engine (significant vs. insignificant) | ✅ Strong | `packages/protocol-engine`, Phase 1 |
| — | Clinician protocol authoring & self-test at implementation | ✅ Exceeds (no-code Rule Studio, simulate, impact report, dual approval) | Phase 2 `domains/protocols` |
| — | Results module — protocol summaries at direct release, priority triage | ✅ Strong | Phase 1 (`domains/generation`, `domains/safety`) |
| — | Patient Messages — classify, tag, summarize for triage | ✅ Strong (deterministic red-flag floor + routing) | Phase 5 `domains/messages` |
| — | Rx module — one-click refills, summarized charts | ✅ Strong (12-step deterministic cascade) | Phase 4 `domains/refills` |
| — | Analytics — acceptance/override tracking, inbox optimization | ✅ Exceeds (governed, approval-gated learning) | Phase 6 `domains/analytics` |
| — | HIPAA / SOC 2 posture, tenant isolation, audit | ✅ Present | `domains/compliance`, `domains/audit`, RLS |
| **G1** | **Billing / coding optimization** — detect missing/under-coded dx, HCC risk capture | ✅ **Closed (Phase 9)** — deterministic `domains/coding`: documented-uncoded + HCC-gap + specificity-upgrade detectors, evidence-linked, human-confirmed review queue, export-gated, analytics-fed | `domains/coding/core.py`, `domains/coding/services.py`, `clinara/api_v1_coding.py` |
| **G2** | **Real EMR connectivity — SMART Backend Services auth** — client-assertion JWT, token cache/refresh, scopes | ✅ **Closed (Phase 7)** — full SMART flow, injected signer/transport, validated against a vendor-emulating token endpoint | `clinara_integration_sdk/smart.py` |
| **G3** | **Real write-back / direct-release delivery** — Epic/Athena inbasket + patient-portal adapters | ✅ **Closed (Phase 7)** — `SmartEhrClient` (FHIR `Task`/`Communication`), retrying `deliver`, idempotent `release_result`, degraded-channel alert | `clinara_integration_sdk/fhir_writeback.py`, `domains/delivery/adapters.py` |
| **G4** | **EHR-embedded clinician surface** — SMART-on-FHIR launch, Epic Showroom / Athena Marketplace, no separate login | ✅ **Closed (Phase 8)** — real SMART EHR-launch + OIDC identity bridge (fail-closed, tenant-isolated, audited), embedded surface, marketplace manifests | `clinara_integration_sdk/smart_launch.py`, `domains/embedded`, `clinara/api_v1_embedded.py` |
| **G5** | **Chart-context panel** — surface relevant chart details in-inbox to eliminate chart digging | ✅ **Closed (Phase 8)** — clinician-facing panel (labs/patient-context/provenance + freshness) over the stored snapshot, beside the item under review | `domains/context/core.py` (`build_context_panel`), `domains/context/services.py` |
| **G6** | **Multi-specialty breadth (30+ ambulatory specialties)** | ✅ **Closed (Phase 10)** — catalog grown to 25 markers; 7 validated, parameterized protocol packs cover **34 ambulatory specialties** (tested coverage); per-tenant threshold customization with no code change, gated so it can never weaken safety | `packages/terminology/markers.py`, `clinical/protocols/specialties/`, `domains/specialties` |
| **G7** | **Data retention & purge** — minimal-necessary retention, 90-day window, BAA-triggered purge | ✅ **Closed (Phase 11)** — deterministic `domains/retention`: per-tenant window policy (90-day raw-inbound default, bounded so it can't be zero/unbounded), scheduled minimization purge (idempotent, tenant-scoped, cascade-aware), BAA-termination hard-purge with a content-hashed certificate of destruction; the append-only audit trail is never a purge target | `domains/retention/core.py`, `domains/retention/services.py`, `clinara/api_v1_retention.py` |

---

## 3. Gap details

### G1 — Billing / Coding Optimization module ✅ (closed in Phase 9)
- **Elaborate:** "Detects missing or under-coded diagnoses through patient context analysis…
  improves documentation integrity and supports compliant risk capture." A revenue-integrity
  module riding on the same chart context.
- **Delivered:** A deterministic `domains/coding` domain that, given the canonical
  `ContextSnapshot` facts + documented problem list + encounter diagnoses, flags three gap
  types as **suggestions in a review queue, never auto-applied to a claim**:
  - `domains/coding/catalog.py` — the codified clinical content (ICD-10 codes, HCC tags,
    the KDIGO eGFR→CKD staging table, the ADA A1c diagnostic threshold). Data, not model
    output, so every suggestion is replayable — the same way `MARKER_SPECS` codifies lab
    thresholds.
  - `domains/coding/core.py` — pure, Django-free detectors: **documented-but-uncoded**
    (active problem whose code is off the encounter), **HCC gap** (a risk-adjustable
    condition *suspected* from a lab value at/over threshold yet undocumented — always
    `requires_provider_confirmation`), and **specificity upgrade** (unspecified code on the
    encounter the chart can sharpen). Two hard anti-upcoding guardrails live here:
    *no-evidence ⇒ no-suggestion* (asserted in `analyze`) and conservative thresholds
    (nothing below the A1c diagnostic cut-off or at eGFR ≥ 60).
  - `domains/coding/services.py` — the governed lifecycle: `analyze_encounter` /
    `analyze_from_snapshot` (rides the immutable snapshot the engine already reasoned over)
    create suggestions `PENDING`; `confirm_suggestion` / `reject_suggestion` are the only
    ways one advances (actor-attributed, audited, event-published); `export_suggestion`
    releases **only** a confirmed suggestion — a pending/rejected one can never be exported.
    Every decision hash-chains an `AuditEvent` and feeds the Phase 6 governed loop as
    `coding` feedback (approve/override), so acceptance/override rates are tracked like every
    other clinician action.
  - `clinara/api_v1_coding.py` — the analyze / review-queue / confirm / reject / export
    endpoints (`/api/v1/coding/*`), tenant-resolved and RLS-scoped.
- **Validation status:** 23 dedicated tests (`apps/api/tests/test_phase9_coding.py`,
  `test_api_coding.py`) covering each detector incl. **negative/no-support cases**, the
  export-before-confirm block, no-auto-apply, idempotent re-analysis, tenant isolation, and
  the analytics hook. Full suite green (153 passed).
- **Invariant held:** no model-driven clinical decision — the suggestions are pure
  deterministic logic over the canonical snapshot; the human confirms before anything leaves
  Clinara (same governance posture as Phase 6).

### G2 — Real EMR connectivity: SMART Backend Services auth ✅ (closed in Phase 7)
- **Elaborate:** Embedded in the EMR via FHIR or direct integration; production Epic/Athena.
- **Delivered:** A complete SMART Backend Services OAuth flow in
  `clinara_integration_sdk/smart.py` — signed JWT client assertion (RFC 7523; `iss=sub=
  client_id`, `aud=token URL`, short expiry, unique `jti`), `client_credentials` grant,
  bearer-token cache with refresh-before-expiry, and scope passthrough. The HTTP call
  (`transport.py`, stdlib `UrllibTransport`), the clock, and the JWT `Signer` are all
  **injected**, so the flow is unit-tested against a vendor-emulating token endpoint and
  points at a live Epic/Athena token URL by config alone.
- **Validation status:** Verified against conformance fakes emulating the Epic/Athena token
  endpoint (no live sandbox credentials in this environment). Dev/test uses the bundled
  `HmacSigner`; production injects an RS384 `Signer` over a vault-held key — the flow is
  identical either way. **Remaining for GA:** wire live sandbox credentials + RS384 signer and
  re-run the same suite against the real endpoints; HL7 v2 MLLP listener against a real feed.
- **Invariant held:** vendor parsing/auth stays in the SDK adapter layer; protocol logic never
  sees it (canonical-in-the-middle, `plan.md §Phase 3`).

### G3 — Real write-back / direct-release delivery adapters ✅ (closed in Phase 7)
- **Elaborate:** The flagship — protocol summaries delivered **at direct release** into the
  patient portal, with tasks/notes written to the clinician inbasket.
- **Delivered:**
  - `clinara_integration_sdk/fhir_writeback.py` — a FHIR R4 write-back client that creates a
    `Task` (care-team inbasket) and a `Communication` (patient-portal message), extracts the
    external id from the response body or `Location` header, applies per-vendor profiles
    (`EPIC`, `ATHENA`), and classifies HTTP failures as **retryable** (429/5xx/network) vs
    **terminal** (4xx).
  - `domains/delivery/adapters.py` — `SmartEhrClient` bridges the existing `EhrClient` seam to
    that FHIR client (channel → resource mapping) so all governance stays in the service.
  - `domains/delivery/services.py` — `deliver` now does **bounded retry with backoff** on
    transient failures (injected sleeper → deterministic), records every `DeliveryAttempt`,
    and emits `DeliverySucceeded`/`DeliveryFailed`. New `release_result` produces **exactly one
    portal message + one EHR task** per approved workflow and delivers both, **idempotently**
    (re-release is a no-op). A write-back failure spike raises a `WriteBackDegraded` operator
    alert (`write_back_health`).
- **Validation status:** End-to-end run + unit/integration tests against a vendor-emulating
  FHIR server (token → `Communication` + `Task` writes → confirmed delivery → events →
  idempotent re-release → cached token). Live Epic/Athena sandbox certification pending
  credentials.
- **Invariant held:** duplicate patient communication is prevented by the existing idempotency
  keying, which every path honors; the adapter speaks only FHIR.

### G4 — EHR-embedded clinician surface ✅ (closed in Phase 8)
- **Elaborate:** "Built directly into your EMR — no new platforms, no extra clicks, no
  additional logins." Available in the Epic Showroom and Athena Marketplace.
- **Delivered:**
  - `clinara_integration_sdk/smart_launch.py` — the pure SMART App Launch (*EHR launch*) flow:
    well-known discovery, authorize-URL shaping (`aud`/`state`/`nonce`/`launch`), code→token
    exchange, and OIDC id_token validation with each check independently enforced (signature
    via an injected `Verifier`, `iss`, `aud`, `exp`, `nonce` — alg-confusion + replay guards).
  - `domains/embedded` — persistence + identity bridge: `EhrConnection` (issuer→tenant
    routing), `EhrIdentityLink` (EHR identity → Clinara user, **RLS-enforced**), and
    `EhrLaunchSession` (the state/nonce handshake + resolved user + hard expiry). `begin_launch`
    resolves the issuer's tenant and mints the redirect; `complete_launch` exchanges the code,
    bridges the identity **fail-closed** (no link ⇒ refused), and stamps an expiry from the EHR
    token so the session cannot outlive the EHR's. Every launch — bridged or denied — is audited
    and event-published (`EhrLaunched`/`EhrLaunchDenied`).
  - `clinara/api_v1_embedded.py` + `clinara/embedded_surface.py` — the SMART `launch`/`callback`
    endpoints (the only unauthenticated surface; the callback establishes the Django session
    directly — **no separate login**), the embedded review surface (`embedded.html`, framed in
    the EHR), and the chart-context endpoint.
  - `clinical/marketplace/{epic-showroom,athena-marketplace}.json` + a deterministic validator
    (`domains/embedded/marketplace.py`) so a malformed listing fails a test, not a submission.
- **Validation status:** End-to-end against a vendor-emulating fake EHR (discovery + token
  endpoint) with an HMAC id_token verifier; production injects an RS256/JWKS `Verifier` by
  config. **Remaining for GA:** live Epic Showroom / Athena Marketplace listing + the RS256/JWKS
  verifier wired to each EHR's published keys.
- **Invariant held:** the bridge **reuses** `domains/identity` (the resolved `User` carries its
  tenant + role); it never forks auth, and tenant isolation of the identity link is enforced at
  the database (RLS).

### G5 — Clinician-facing chart-context panel ✅ (closed in Phase 8)
- **Elaborate:** Surfaces relevant chart details dynamically in the inbox view — "eliminates
  manual chart digging for medication, referral, and testing decisions."
- **Delivered:** `build_context_panel` (`domains/context/core.py`) — a pure, presentation-only
  projection of the immutable `ContextSnapshot` into the labs (value/unit/reference range/trend
  + in/below/above-range status computed from the snapshot's own range), patient context, and
  provenance/freshness a clinician needs beside the item under review. `chart_context_panel`
  (`domains/context/services.py`) reads the stored `ContextSnapshotRecord`; the embedded surface
  renders it beside the review item via `GET /api/v1/embedded/context/{workflow_id}`. It adds
  **nothing** — every value shown is drawn verbatim from the snapshot the engine already
  reasoned over — so the panel is exactly what the decision was based on. Low clinical risk,
  high UX value.

### G6 — Multi-specialty protocol breadth ✅ (closed in Phase 10)
- **Elaborate:** "Rules-based protocols across 30+ ambulatory specialties."
- **Delivered:** Content + governance, no engine change (the invariant held):
  - `packages/terminology/markers.py` — the canonical catalog grew from 6 markers to **25**
    across ambulatory panels (thyroid, extended lipids, hepatic, hematology, coagulation,
    inflammatory, electrolytes), each with canonical unit, reference range, LOINC seed codes,
    and unit conversions. `LAB_FACT_ALIAS` is now **derived** from the catalog, so adding a
    marker is a pure data change — the crown-jewel evaluator is never edited to grow breadth.
    New conventional adult critical bands (sodium, calcium, hemoglobin, platelets, WBC, INR)
    extend the un-weakenable safety floor (`clinara_protocol_engine.critical`).
  - `clinical/protocols/specialties/*.yaml` — **7 parameterized protocol packs** authored as
    versioned data (thyroid, lipids, hepatic, hematology, coagulation, inflammatory, renal/
    electrolytes). Each rule is specialty-scoped and carries `{param: <name>}` threshold
    placeholders with pack defaults; each pack ships **required positive + negative + critical
    test cases**. Their `scope.specialties` collectively cover **34 ambulatory specialties**.
  - `domains/specialties` — the registry (`catalog.py`, 34 specialties as data), the pure pack
    mechanics (`core.py`: `bind_parameters`, `validate_pack`, `coverage`), and the governed
    service (`services.py`): a per-tenant `SpecialtyThresholdPolicy` lets a practice retune a
    threshold **without any code change**, and `set_threshold` re-runs the full pack activation
    gate (bind → parse → `assert_cannot_weaken_safety` → required tests) before persisting, so
    a customization can never down-classify a critical value or break a required test.
    `resolve_rules` composes the base rules with each pack bound to the tenant's effective
    thresholds — the exact, replayable rule set the engine evaluates (wired into
    `domains/workflows/services.py`).
  - `clinara/api_v1_specialties.py` — browse the registry + coverage, inspect the validated
    packs and their tenant-effective thresholds, and customize a threshold (`/api/v1/
    specialties/*`), tenant-resolved and RLS-scoped.
- **Validation status:** 23 dedicated tests (`apps/api/tests/test_phase10_specialties.py`,
  `test_api_specialties.py`) + 9 catalog/critical tests (`packages/…/test_phase10_*`): every
  pack passes the activation gate, all 34 specialties are covered, the same snapshot yields a
  different governed decision under two threshold policies (proven through the real ingest
  pipeline), unsafe overrides are rejected, and tenant isolation holds. Full suite green (176
  API + package tests passed).
- **Invariant held:** no model-driven clinical decision — packs are deterministic rules over
  the canonical snapshot; every threshold is data bound before evaluation, and the critical
  floor still runs first and un-weakenably. Breadth scales through the Rule Studio governance,
  not engineering.

### G7 — Data retention & purge lifecycle ✅ (closed in Phase 11)
- **Elaborate:** "Minimal necessary data retained for 90 days; fully purged on termination
  per BAA."
- **Delivered:** A deterministic `domains/retention` domain that owns the whole data lifecycle
  without introducing any model-driven decision — what gets destroyed is a pure function of
  (policy, clock, data):
  - `domains/retention/catalog.py` — the codified retention **schedule as data**: every
    purgeable category with its minimal-necessary default window (raw inbound PHI = **90 days**,
    derived clinical records = 365), whether the daily job sweeps it (`windowed`) or it is
    termination-only, plus the hard `MIN`/`MAX` bounds. Adding a category is a data change, not
    an engine edit — the same posture as `MARKER_SPECS` and `coding/catalog.py`.
  - `domains/retention/core.py` — pure, Django-free logic: `resolve_windows` (defaults overlaid
    with overrides), `validate_window` (rejects unknown/zero/unbounded windows before anything
    is touched), `cutoff_for`/`is_expired` (deterministic, boundary-safe), and `build_certificate`
    — a content-hashed **certificate of destruction** whose digest is recomputable by an auditor
    (same tamper-evidence as the compliance attestation digest).
  - `domains/retention/services.py` — the governed lifecycle: a per-tenant `RetentionPolicy`
    (`set_retention_window`, versioned + audited), `run_scheduled_purge` (sweeps every windowed
    category past its per-tenant cutoff — deterministic, **idempotent**, tenant-bound, cascade-
    aware; `dry_run` for proof-of-scope), and `terminate_tenant` (BAA hard-purge of **all** PHI +
    a persisted `CertificateOfDestruction`, marking the policy terminated). Every purge writes one
    hash-chained `data_purge` `AuditEvent`, publishes `DataPurged`/`TenantDataPurged`, and the
    certificate records how many audit events were **retained** — the append-only audit trail is
    never itself a purge target. `PURGE_TARGETS` maps each category to its concrete ORM model(s).
  - `domains/retention/tasks.py` + `management/commands/purge_expired.py` — the scheduled path
    (Celery beat, daily) and an ops/backfill command; both bind each tenant's RLS context before
    touching a row. `clinara/api_v1_retention.py` — inspect/tune the policy, run/dry-run a purge,
    review purge history, and (admin-gated) execute a certified termination (`/api/v1/retention/*`).
- **Validation status:** 24 dedicated tests (`apps/api/tests/test_phase11_retention.py`,
  `test_api_retention.py`) covering the pure bounds/cutoff/certificate logic, expired-purged-vs-
  fresh-kept, cascade of child rows, idempotent re-run, dry-run-doesn't-delete, audit-trail-
  preserved, **tenant isolation** (a purge cannot cross tenants), the full certified termination,
  the auditor's certificate-hash recomputation, and the admin role gate. Full suite green
  (200 passed).
- **Invariant held:** no model-driven decision — the purge is pure deterministic logic; it is
  bounded, tenant-scoped, audited, and the audit trail survives every purge (§1).

---

## 4. Closure plan (Phases 7–11)

Sequencing rationale: **G2/G3 (real connectivity)** unblock the flagship "direct release"
value and everything downstream, so they come first. **G4/G5 (embedded surface + context
panel)** ride on that connectivity. **G1 (billing)** and **G6 (specialty breadth)** are
parallelizable revenue/content tracks. **G7 (retention/purge)** is compliance-gating for any
real customer and is sequenced before go-live.

| Phase | Title | Closes | Depends on | Parallelizable with |
|---|---|---|---|---|
| **7** ✅ | Real EMR Connectivity | G2, G3 | Phase 3 rails | — |
| **8** ✅ | EHR-Embedded Clinician Surface | G4, G5 | Phase 7 | Phase 9 |
| **9** ✅ | Billing & Coding Intelligence | G1 | Phase 5 context | Phase 8 |
| **10** ✅ | Specialty Protocol Breadth | G6 | Phase 2 Studio | Phases 8–9 |
| **11** ✅ | Data Lifecycle & Compliance Hardening | G7 | — (cross-cutting) | all |

---

### Phase 7 — Real EMR Connectivity

**Status:** ✅ **Implemented (validated against vendor-emulating conformance fakes; live
sandbox certification pending credentials).** The stubbed write-back edge is replaced by a
real SMART-on-FHIR client stack: SMART Backend Services auth, a FHIR R4 write-back client
(`Task` + `Communication`), a `SmartEhrClient` bridging the delivery seam, retrying/confirmed
delivery, idempotent direct-release of one portal message + one EHR task per result, and a
degraded-channel operator alert. All new outbound logic is pure and dependency-injected
(HTTP transport, JWT signer, clock), so it runs against fakes today and a live Epic/Athena
endpoint by configuration alone. See the README "Current status — Phase 7" section.

**Objective:** Replace the stubbed delivery adapters with production SMART-on-FHIR write-back
+ patient-portal delivery, so protocol summaries actually reach patients at direct release.
**Why now:** The flagship value ("36% less inbox time") requires real channels; every later
phase assumes them.

#### Workstreams
1. **SMART backend-services auth** (Integration) — ✅ JWT client-assertion, token
   cache/refresh, scope management (`clinara_integration_sdk/smart.py`).
2. **FHIR write-back client** (Integration) — ✅ `Task` + `Communication` writes, id
   extraction, Epic/Athena profiles, retryable-vs-terminal classification
   (`clinara_integration_sdk/fhir_writeback.py`).
3. **Epic & Athena write-back adapters** (Integration) — ✅ `SmartEhrClient` over the delivery
   `EhrClient` seam; honors existing idempotency keying (`domains/delivery/adapters.py`).
4. **Retrying, confirmed delivery + direct release** (Integration) — ✅ bounded retry/backoff,
   `release_result` (one portal + one task, idempotent), `WriteBackDegraded` alert
   (`domains/delivery/services.py`).
5. **HL7 v2 MLLP listener against a real feed** (Integration) — ⏳ deferred to live-sandbox
   certification (parser already exists from Phase 3; the socket listener needs a real feed).

#### Deliverables
- SMART client stack in `clinara_integration_sdk` (transport, smart, fhir_writeback, retry),
  fully unit-tested (`packages/integration-sdk/tests/test_{smart,fhir_writeback,retry}.py`).
- Confirmed write-back of a task + patient-portal message end-to-end, with retry on transient
  failure and an operator alert on a write-back spike
  (`apps/api/tests/test_phase7_smart_delivery.py`).
- `/api/v1/workflows/{id}/release` and `/api/v1/delivery/health` endpoints.

#### Exit / acceptance gate
- [x] SMART backend auth obtains + refreshes tokens. *(assertion shape, grant, cache, refresh,
  scope, error classification — `test_smart.py`; token reuse across deliveries —
  `test_token_is_reused_across_deliveries`. Validated against emulated Epic/Athena token
  endpoints; live-sandbox run pending credentials.)*
- [x] A released result produces exactly one portal message + one inbasket task (idempotent).
  *(`release_result`; `test_release_result_produces_one_portal_and_one_task_idempotently`;
  end-to-end smoke.)*
- [x] Write-back failures surface as delivery events + operator alert — zero silent loss.
  *(retry then `DeliveryFailed`; `WriteBackDegraded` on spike —
  `test_transient_failure_retries_then_fails_with_zero_silent_loss`,
  `test_write_back_spike_raises_degraded_alert`.)*
- [x] All adapters keep vendor quirks out of protocol logic (canonical-in-the-middle verified).
  *(adapter speaks only FHIR; `EPIC`/`ATHENA` profiles isolate quirks —
  `test_athena_profile_adds_communication_category`.)*

---

### Phase 8 — EHR-Embedded Clinician Surface

**Status:** ✅ **Implemented (validated against a vendor-emulating fake EHR; live marketplace
listing + RS256/JWKS verifier pending).** A clinician now opens Clinara **inside** their EHR via
a real SMART-on-FHIR EHR launch: the app discovers the EHR's endpoints, redirects to authorize,
exchanges the code, validates the OIDC id_token (signature/`iss`/`aud`/`exp`/`nonce`), and
bridges the EHR identity to a Clinara user — fail-closed, tenant-isolated, audited — establishing
the session with **no separate login** and an expiry bounded to the EHR token. The embedded
surface renders the review queue with a live chart-context panel beside each item, and Epic
Showroom / Athena Marketplace manifests are packaged and validated. All protocol/HTTP/crypto is
pure and injected (transport, id_token `Verifier`, clock, state/nonce factories), so it runs
against fakes today and a live Epic/Athena endpoint by configuration alone. See the README
"Current status — Phase 8" section.

**Objective:** Let clinicians work Clinara **inside** their EHR — a SMART-on-FHIR launch that
embeds the review surface with a live chart-context panel, no extra login. **Why now:** Depends
on Phase 7 connectivity; matches Elaborate's "native in your EMR, no additional logins"
distribution.

#### Workstreams
1. **SMART-on-FHIR EHR launch** (Frontend + Integration) — ✅ OAuth2 launch/redirect + code
   exchange + OIDC id_token validation, session bridge to Clinara identity preserving
   tenant/role (`clinara_integration_sdk/smart_launch.py`, `domains/embedded`).
2. **Embeddable review surface** (Frontend) — ✅ results/messages/refills review embedded in the
   EHR app frame (`clinara/templates/embedded.html`, `clinara/embedded_surface.py`).
3. **Chart-context panel (G5)** (Backend + Frontend) — ✅ read API rendering `ContextSnapshot`
   (labs + patient context + provenance/freshness) beside the item under review
   (`domains/context/core.py:build_context_panel`, `GET /api/v1/embedded/context/{id}`).
4. **Marketplace packaging** (Integration) — ✅ Epic Showroom listing + Athena Marketplace app
   manifest + deterministic validator (`clinical/marketplace/`, `domains/embedded/marketplace.py`).

#### Deliverables
- Clinician launches Clinara from within a (fake/sandbox) EHR; identity bridged, tenant-isolated,
  audited; session established with no separate login and a token-bounded expiry
  (`apps/api/tests/test_phase8_embedded_surface.py`, `packages/integration-sdk/tests/test_smart_launch.py`).
- Chart-context panel renders live snapshot data with provenance/freshness.
- Epic Showroom + Athena Marketplace manifests validated.
- `GET /api/v1/smart/launch`, `GET /api/v1/smart/callback`, `GET /api/v1/embedded/session`,
  `GET /api/v1/embedded/context/{workflow_id}` endpoints + admin registration endpoints.

#### Exit / acceptance gate
- [x] EHR launch bridges identity → correct Clinara tenant/role; audit records the launch.
  *(identity bridge via `EhrIdentityLink`, fail-closed when unlinked; `ehr_launch` audit +
  `EhrLaunched` event — `test_complete_launch_bridges_identity_to_correct_user_and_audits`,
  `test_unlinked_identity_is_refused_fail_closed`, `test_identity_link_does_not_cross_tenants`.)*
- [x] Context panel shows relevant chart detail with freshness/provenance; no chart digging.
  *(`build_context_panel` labs + patient context + provenance; served over the stored snapshot —
  `test_build_context_panel_groups_labs_and_provenance`,
  `test_context_panel_service_reads_snapshot_record`,
  `test_end_to_end_launch_bridges_session_and_serves_context`.)*
- [x] No separate login; session scoped and expires with the EHR session. *(callback calls
  `login()` directly and caps session at the token lifetime; `get_live_session` transitions a
  lapsed session to EXPIRED — `test_end_to_end_launch_bridges_session_and_serves_context`,
  `test_get_live_session_expires_and_transitions`.)*

---

### Phase 9 — Billing & Coding Intelligence

**Status:** ✅ **Implemented (deterministic, evidence-linked, human-confirmed; full suite
green).** A new `domains/coding` module turns the canonical chart context into revenue-integrity
suggestions in an inert review queue — documented-but-uncoded, HCC/risk-adjustment gaps
(suspected-but-unaddressed), and specificity upgrades — each evidence-linked and impossible to
auto-apply. The clinical thresholds/codes are codified as data (`catalog.py`), the detectors are
pure and Django-free (`core.py`), and the governed lifecycle (`services.py`) creates every
suggestion `PENDING`, requires a human confirm/reject, gates export on confirmation, audits every
decision, and feeds acceptance/override into the Phase 6 loop. See the README "Current status —
Phase 9" section.

**Objective:** Add the deterministic revenue-integrity module — detect missing/under-coded
diagnoses and HCC/risk-capture gaps as human-confirmed suggestions. **Why now:** Rides on the
same chart context (Phase 5/7); parallelizable with Phase 8.

#### Workstreams
1. **Coding domain** (Backend) — ✅ new `domains/coding`; deterministic gap rules over the
   canonical snapshot + problem list + encounter dx (`core.py`, `catalog.py`).
2. **Gap detectors** (Clinical + Backend) — ✅ documented-but-uncoded, HCC suspecting
   (suspected-but-unaddressed), specificity upgrades — each evidence-linked, with negative
   (no-support) cases proven (`detect_documented_uncoded`, `detect_hcc_gaps`,
   `detect_specificity_upgrades`).
3. **Review queue + governance** (Backend + Frontend) — ✅ suggestions are inert/pending;
   human confirm/reject required; export gated on confirmation; full hash-chained audit
   (`services.py`, `clinara/api_v1_coding.py`).
4. **Analytics hook** (Backend) — ✅ confirm→approve / reject→override captured as `coding`
   feedback so acceptance/override rates flow into the Phase 6 governed dashboards
   (`domains/analytics/services.py` workflow-type loop).

#### Deliverables
- ✅ Suggestion queue with evidence links; nothing auto-applied to a claim
  (`CodingSuggestionRecord`, `/api/v1/coding/*`).
- ✅ Deterministic, unit-tested detectors; upcoding guardrails (no-evidence-no-suggestion +
  conservative thresholds) — `test_phase9_coding.py`, `test_api_coding.py` (23 tests).

#### Exit / acceptance gate
- [x] Every suggestion is deterministic, evidence-linked, and human-confirmed before export.
  *(pure detectors over the snapshot; `export_suggestion` raises unless status is `CONFIRMED` —
  `test_export_requires_confirmation_gate`, `test_analyze_review_confirm_export_flow`.)*
- [x] No suggestion can be auto-applied; audit shows actor + evidence for each acceptance.
  *(all suggestions created `PENDING`; `confirm_suggestion` writes `coding_suggestion_confirmed`
  audit with actor + evidence — `test_analyze_creates_pending_queue_nothing_auto_applied`,
  `test_confirm_advances_audits_and_feeds_analytics_loop`.)*
- [x] Detectors covered by unit tests incl. negative (no-support → no-suggestion) cases.
  *(A1c below threshold, eGFR ≥ 60, already-documented, and no-unspecified-code cases all
  yield nothing — `test_hcc_gap_*`, `test_specificity_upgrade_silent_without_the_unspecified_code`,
  `test_analyze_is_deterministic_evidence_linked_and_empty_on_no_signal`.)*

---

### Phase 10 — Specialty Protocol Breadth

**Status:** ✅ **Implemented (deterministic, data-driven, human-governed; full suite green).**
The canonical marker catalog grew from 6 to 25 markers, and 7 parameterized, specialty-scoped
protocol packs (`clinical/protocols/specialties/`) now cover **34 ambulatory specialties**
(tested coverage). A new `domains/specialties` module adds the specialty registry, the pure
pack activation gate (`validate_pack`: bind → parse → `assert_cannot_weaken_safety` → required
tests), and **per-tenant threshold customization with no code change** — a
`SpecialtyThresholdPolicy` whose overrides are bound into rules at load time and re-validated
against the full gate before they can go live. `resolve_rules` composes the base rules with the
tenant-bound packs into the exact rule set the engine evaluates (wired into the workflow path).
No engine code changed to grow breadth. See the README "Current status — Phase 10" section.

**Objective:** Grow authored, clinically-validated protocol content from ~6 markers to 30+
ambulatory specialties, via the existing Rule Studio governance. **Why now:** Content/validation
effort, not engine work; parallelizable once Studio (Phase 2) is proven.

#### Workstreams
1. **Catalog expansion** (Terminology) — ✅ +19 markers with units/ranges/LOINC + conversions;
   `LAB_FACT_ALIAS` derived from the catalog; new critical bands
   (`packages/terminology/markers.py`, `clinara_protocol_engine/critical.py`).
2. **Protocol authoring** (Clinical Programmers) — ✅ 7 parameterized packs, each specialty-
   scoped with required positive/negative/critical test cases (`clinical/protocols/specialties/`).
3. **Clinical validation** (Clinical) — ✅ pack activation gate = the Rule Studio deploy gate
   (`core.validate_pack`); `services.validate_all()` proves the whole library passes.
4. **Content governance** (Backend) — ✅ per-tenant threshold customization without code change
   (`SpecialtyThresholdPolicy`, gated `set_threshold`, `resolve_rules`); pack versioning + the
   Phase 6 acceptance loop still apply to every specialty action.

#### Deliverables
- ✅ 7 specialty packs behind the activation gate; each with passing required test cases;
  34/34 registered specialties covered (`services.coverage_report()`).
- ✅ Documented authoring playbook so breadth scales without engineering
  (`docs/protocols/specialty-pack-authoring.md`).

#### Exit / acceptance gate
- [x] Each pack passes Rule Studio required tests + dual clinical/engineering approval.
  *(`validate_pack` runs `run_test_cases` over each pack's required cases; the pack gate mirrors
  `domains/protocols.deploy` (dual-approval + tests + conflict) — `test_every_pack_passes_the_
  activation_gate`, `test_packs_are_listed_and_all_validate`.)*
- [x] No pack can down-classify a critical (`assert_cannot_weaken_safety` holds).
  *(every pack rule is bounded above the critical floor; critical values escalate first —
  `test_no_pack_rule_can_downclassify_a_critical_value`; the guard itself bites on a crafted bad
  rule — `test_the_safety_guard_actually_bites_on_a_crafted_bad_rule`.)*
- [x] Per-tenant threshold customization works without code change.
  *(`{param}` overrides bound at load time; same snapshot → different governed decision under two
  policies, proven through the real ingest pipeline; unsafe overrides rejected —
  `test_per_tenant_threshold_changes_the_engine_decision_no_code_change`,
  `test_end_to_end_two_tenants_get_different_classifications`,
  `test_set_threshold_rejects_an_override_that_breaks_a_required_test`.)*

---

### Phase 11 — Data Lifecycle & Compliance Hardening

**Status:** ✅ **Implemented (deterministic, tenant-scoped, audited, certified; full suite
green).** A new `domains/retention` module owns the whole data lifecycle: a per-tenant retention
policy (minimal-necessary 90-day raw-inbound default, bounded so it can never be zero or
unbounded), a scheduled minimization purge that sweeps every windowed PHI category past its
per-tenant cutoff (deterministic, idempotent, tenant-bound, cascade-aware, with a `dry_run`
proof-of-scope path), and a BAA-termination hard-purge that destroys all of a tenant's PHI and
issues a content-hashed certificate of destruction. Every purge appends one hash-chained
`data_purge` audit event and publishes a domain event; the append-only audit trail is never a
purge target and the certificate records how many audit events were retained. The pure
bounds/cutoff/certificate logic (`core.py`) and the retention schedule (`catalog.py`) are
Django-free and exhaustively unit-tested; the scheduled path runs on a Celery beat and via a
management command. No model-driven decision anywhere (the §1 invariant holds). See the README
"Current status — Phase 11" section.

**Objective:** Implement minimal-necessary retention, scheduled purge, and BAA-termination
hard-purge with certificate of destruction. **Why now:** Compliance-gating for any real
customer; cross-cutting, can run alongside all phases but must land before GA sign-off with real
PHI.

#### Workstreams
1. **Retention policy** (Backend) — ✅ per-tenant `RetentionPolicy` (JSON window overrides +
   version), minimal-necessary defaults in `catalog.py` (90 days for raw inbound), bounded and
   validated in `core.validate_window` (`domains/retention/{catalog,core,models,services}.py`).
2. **Scheduled minimization/purge** (Backend) — ✅ `run_scheduled_purge` sweeps expired rows per
   category (cascade-aware, idempotent), tenant-bound (RLS), on a Celery beat + `purge_expired`
   command; the audit trail is preserved (`services.py`, `tasks.py`, `management/commands/`).
3. **BAA-termination purge** (Backend + Compliance) — ✅ `terminate_tenant` hard-purges all PHI
   and persists a content-hashed `CertificateOfDestruction`; policy marked terminated.
4. **Verification** (Compliance) — ✅ `dry_run` proof-of-scope, per-category counts + cutoffs on
   every `PurgeRun`, retained-audit-event count on the certificate, recomputable digest.

#### Deliverables
- ✅ Retention policy enforced by a scheduled job; purge is idempotent and audited
  (`RetentionPolicy`, `PurgeRun`, `/api/v1/retention/*`).
- ✅ BAA-termination purge produces a certificate of destruction (`CertificateOfDestruction`,
  `terminate_tenant`) — verified in `test_phase11_retention.py`, `test_api_retention.py` (24 tests).

#### Exit / acceptance gate
- [x] PHI past the retention window is purged on schedule; audit integrity preserved.
  *(expired rows purged, fresh kept, children cascaded, audit trail only grows —
  `test_scheduled_purge_removes_expired_keeps_fresh`,
  `test_scheduled_purge_cascades_children_and_is_audited_and_evented`,
  `test_audit_trail_is_never_purged`.)*
- [x] Termination purge is complete, tenant-scoped, and certified.
  *(all PHI regardless of age destroyed; content-hashed certificate; auditor recomputes the
  digest from stored lines — `test_terminate_purges_all_phi_certifies_and_preserves_audit`,
  `test_certificate_hash_matches_the_pure_core_recomputation`.)*
- [x] Purge operations are themselves audited and cannot cross tenant boundaries.
  *(every purge writes a `data_purge` audit + `DataPurged`/`TenantDataPurged` event; a purge for
  tenant A leaves tenant B untouched — `test_purge_cannot_cross_tenant_boundaries`,
  `test_purge_all_tenants_skips_terminated_and_sweeps_active`.)*

---

## 5. Summary

Clinara has already replicated Elaborate's **hardest, most defensible layer** — the
deterministic, auditable protocol core with governance — and in the Rule Studio and governed
learning loop it **exceeds** what Elaborate publicly documents. **With Phase 11 landed, every
identified gap (G1–G7) is closed** — including the final one, the **compliance lifecycle**
(retention/purge, G7) — without abandoning the deterministic architecture. The replica is at
functional parity while preserving the invariant in §1.

**Progress:** **Phases 7, 8, 9, 10, and 11 are implemented and tested.** Phase 7 (Real EMR Connectivity,
G2 + G3) delivered the SMART-on-FHIR write-back edge (auth + `Task`/`Communication` writes +
retrying, idempotent, alerting delivery). Phase 8 (EHR-Embedded Clinician Surface, G4 + G5)
delivered the inbound half: a real SMART EHR launch with OIDC identity bridging (fail-closed,
tenant-isolated, audited, no separate login, EHR-bounded session), a clinician-facing
chart-context panel over the immutable snapshot, an embedded review surface, and validated
Epic/Athena marketplace manifests. Phase 9 (Billing & Coding Intelligence, G1) added the
deterministic revenue-integrity module: evidence-linked documented-uncoded / HCC-gap /
specificity-upgrade detectors over the canonical snapshot, an inert human-confirmed review queue
with an export-on-confirmation gate, full audit, and an acceptance/override feedback hook into the
Phase 6 loop — no model-driven coding decision anywhere. Phase 10 (Specialty Protocol Breadth,
G6) grew the catalog to 25 markers and authored 7 validated, parameterized protocol packs
covering 34 ambulatory specialties, plus per-tenant threshold customization that is bound as
data at load time and gated so it can never weaken safety — all without an engine change.
Phase 11 (Data Lifecycle & Compliance Hardening, G7) added the deterministic `domains/retention`
module: a bounded per-tenant retention policy, a scheduled minimization purge (idempotent,
tenant-scoped, cascade-aware), and a BAA-termination hard-purge with a content-hashed certificate
of destruction — every purge audited and event-published, the append-only audit trail never a
purge target. Phases 7/8 run behind injected transport/verifier/clock seams, validated against
vendor-emulating fakes; live Epic/Athena sandbox + marketplace certification (and the RS256/JWKS
id_token verifier) are the remaining GA steps for those gaps. **No identified gap remains open.**
