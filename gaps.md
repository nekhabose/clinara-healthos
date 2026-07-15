# Clinara HealthOS — Gap Analysis & Closure Plan
### Feature parity vs. Elaborate (elaborate.com), and the phased plan to reach it

**Author's note (2026-07-15):** This document benchmarks the current implementation
(Phases 0–6 + GA Hardening + Phase 7 Real EMR Connectivity + Phase 8 EHR-Embedded Surface, all
landed) against **Elaborate** — the product Clinara is a replica of — identifies every remaining
gap, and lays out a phase-by-phase plan to close them. It is a companion to [`plan.md`](plan.md)
and continues its phase numbering (next open phase is **Phase 9**). Read `plan.md` first for the
architectural north star; this document assumes it.

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
| **G1** | **Billing / coding optimization** — detect missing/under-coded dx, HCC risk capture | ❌ **Missing** — only a "billing" message *category* exists | `domains/messages/core.py:42` |
| **G2** | **Real EMR connectivity — SMART Backend Services auth** — client-assertion JWT, token cache/refresh, scopes | ✅ **Closed (Phase 7)** — full SMART flow, injected signer/transport, validated against a vendor-emulating token endpoint | `clinara_integration_sdk/smart.py` |
| **G3** | **Real write-back / direct-release delivery** — Epic/Athena inbasket + patient-portal adapters | ✅ **Closed (Phase 7)** — `SmartEhrClient` (FHIR `Task`/`Communication`), retrying `deliver`, idempotent `release_result`, degraded-channel alert | `clinara_integration_sdk/fhir_writeback.py`, `domains/delivery/adapters.py` |
| **G4** | **EHR-embedded clinician surface** — SMART-on-FHIR launch, Epic Showroom / Athena Marketplace, no separate login | ✅ **Closed (Phase 8)** — real SMART EHR-launch + OIDC identity bridge (fail-closed, tenant-isolated, audited), embedded surface, marketplace manifests | `clinara_integration_sdk/smart_launch.py`, `domains/embedded`, `clinara/api_v1_embedded.py` |
| **G5** | **Chart-context panel** — surface relevant chart details in-inbox to eliminate chart digging | ✅ **Closed (Phase 8)** — clinician-facing panel (labs/patient-context/provenance + freshness) over the stored snapshot, beside the item under review | `domains/context/core.py` (`build_context_panel`), `domains/context/services.py` |
| **G6** | **Multi-specialty breadth (30+ ambulatory specialties)** | ⚠️ Partial — `specialty` plumbed end-to-end; protocol *content* ≈ 6 lab markers | `domains/context/core.py:32`, `MARKER_SPECS` |
| **G7** | **Data retention & purge** — minimal-necessary retention, 90-day window, BAA-triggered purge | ❌ **Missing** — no retention/purge job found | — |

---

## 3. Gap details

### G1 — Billing / Coding Optimization module ❌
- **Elaborate:** "Detects missing or under-coded diagnoses through patient context analysis…
  improves documentation integrity and supports compliant risk capture." A revenue-integrity
  module riding on the same chart context.
- **Current state:** No coding/diagnosis-gap logic exists. `BILLING` appears only as a
  patient-message *category* used for routing (`domains/messages/core.py:42`), not as
  chart analysis.
- **Missing:** A deterministic `domains/coding` domain that, given the canonical
  `ContextSnapshot` + problem list + encounter dx, flags (a) documented-but-uncoded
  conditions, (b) HCC/risk-adjustment gaps (suspected-but-unaddressed), (c) specificity
  upgrades — as **suggestions in a review queue**, never auto-applied to a claim.
- **Risk:** Coding suggestions have compliance/audit exposure (upcoding). Must be
  deterministic, evidence-linked, and human-confirmed — same governance posture as Phase 6.

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

### G6 — Multi-specialty protocol breadth ⚠️
- **Elaborate:** "Rules-based protocols across 30+ ambulatory specialties."
- **Current state:** The *mechanism* is specialty-aware end-to-end (`specialty` threaded
  through context, workflows, and `User.specialties`; engine accepts a `specialty` marker).
  The *content* is ≈6 lab markers (A1c, glucose, creatinine, eGFR, potassium, LDL).
- **Missing:** Authored, clinically-validated protocol packs per specialty (cardiology,
  endocrinology, nephrology, primary care, etc.). This is a **content + clinical-validation**
  effort executed through the existing Phase 2 Rule Studio, not new engine code.
- **Risk:** Clinical accuracy at breadth — every pack goes through Rule Studio's dual-approval
  and required test cases; no shortcut around governance.

### G7 — Data retention & purge lifecycle ❌
- **Elaborate:** "Minimal necessary data retained for 90 days; fully purged on termination
  per BAA."
- **Current state:** Compliance/audit domains exist, but no retention window or purge job was
  found.
- **Missing:** Per-tenant retention policy, a scheduled minimization/purge job (raw inbound
  messages, PHI beyond the necessary window), and a BAA-termination hard-purge with an
  auditable certificate of destruction.
- **Risk:** Purge must not break audit-trail integrity or tenant isolation; must be
  provably scoped and logged.

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
| **9** | Billing & Coding Intelligence | G1 | Phase 5 context | Phase 8 |
| **10** | Specialty Protocol Breadth | G6 | Phase 2 Studio | Phases 8–9 |
| **11** | Data Lifecycle & Compliance Hardening | G7 | — (cross-cutting) | all |

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

**Status:** ⏳ Planned. **Objective:** Add the deterministic revenue-integrity module —
detect missing/under-coded diagnoses and HCC/risk-capture gaps as human-confirmed suggestions.
**Why now:** Rides on the same chart context (Phase 5/7); parallelizable with Phase 8.

#### Workstreams
1. **Coding domain** (Backend) — new `domains/coding`; deterministic gap rules over the
   canonical snapshot + problem list + encounter dx.
2. **Gap detectors** (Clinical + Backend) — documented-but-uncoded, HCC suspecting
   (suspected-but-unaddressed), specificity upgrades — each evidence-linked.
3. **Review queue + governance** (Backend + Frontend) — suggestions are inert/pending;
   human confirmation required before anything leaves Clinara; full audit.
4. **Analytics hook** (Backend) — acceptance/override rates feed the Phase 6 governed loop.

#### Deliverables
- Suggestion queue with evidence links; nothing auto-applied to a claim.
- Deterministic, unit-tested detectors; upcoding guardrails (specificity/support required).

#### Exit / acceptance gate
- [ ] Every suggestion is deterministic, evidence-linked, and human-confirmed before export.
- [ ] No suggestion can be auto-applied; audit shows actor + evidence for each acceptance.
- [ ] Detectors covered by unit tests incl. negative (no-support → no-suggestion) cases.

---

### Phase 10 — Specialty Protocol Breadth

**Status:** ⏳ Planned. **Objective:** Grow authored, clinically-validated protocol content
from ~6 markers to 30+ ambulatory specialties, via the existing Rule Studio. **Why now:**
Content/validation effort, not engine work; parallelizable once Studio (Phase 2) is proven.

#### Workstreams
1. **Specialty prioritization** (Clinical) — order specialties by customer demand/volume.
2. **Protocol authoring** (Clinical Programmers) — pack per specialty in Rule Studio with
   required test cases.
3. **Clinical validation** (Clinical) — dual-approval activation per pack; parity simulation
   against real charts.
4. **Content governance** (Backend) — versioning, per-tenant threshold customization, and
   the acceptance-rate feedback loop per pack.

#### Deliverables
- N specialty packs live behind dual-approval; each with passing test cases + impact report.
- Documented authoring playbook so breadth scales without engineering involvement.

#### Exit / acceptance gate
- [ ] Each pack passes Rule Studio required tests + dual clinical/engineering approval.
- [ ] No pack can down-classify a critical (`assert_cannot_weaken_safety` holds).
- [ ] Per-tenant threshold customization works without code change.

---

### Phase 11 — Data Lifecycle & Compliance Hardening

**Status:** ⏳ Planned. **Objective:** Implement minimal-necessary retention, scheduled purge,
and BAA-termination hard-purge with certificate of destruction. **Why now:** Compliance-gating
for any real customer; cross-cutting, can run alongside all phases but must land before GA
sign-off with real PHI.

#### Workstreams
1. **Retention policy** (Backend) — per-tenant policy model; default minimal-necessary window
   (e.g. 90 days for raw inbound).
2. **Scheduled minimization/purge** (Backend) — job that purges raw messages/PHI past window
   without breaking audit-trail integrity or tenant isolation.
3. **BAA-termination purge** (Backend + Compliance) — hard-purge on offboarding; auditable
   certificate of destruction.
4. **Verification** (Compliance) — proof of scope: what was purged, what audit metadata is
   retained, tenant-scoped.

#### Deliverables
- Retention policy enforced by a scheduled job; purge is idempotent and audited.
- BAA-termination purge produces a certificate of destruction.

#### Exit / acceptance gate
- [ ] PHI past the retention window is purged on schedule; audit integrity preserved.
- [ ] Termination purge is complete, tenant-scoped, and certified.
- [ ] Purge operations are themselves audited and cannot cross tenant boundaries.

---

## 5. Summary

Clinara has already replicated Elaborate's **hardest, most defensible layer** — the
deterministic, auditable protocol core with governance — and in the Rule Studio and governed
learning loop it **exceeds** what Elaborate publicly documents. The remaining gaps are
**integration surface** (real EMR connectivity + embedded launch), **one missing module**
(billing/coding), **compliance lifecycle** (retention/purge), and **protocol-content
breadth** — none of which require abandoning the deterministic architecture. Closing Phases
7–11 brings the replica to functional parity while preserving the invariant in §1.

**Progress:** **Phases 7 and 8 are implemented and tested.** Phase 7 (Real EMR Connectivity,
G2 + G3) delivered the SMART-on-FHIR write-back edge (auth + `Task`/`Communication` writes +
retrying, idempotent, alerting delivery). Phase 8 (EHR-Embedded Clinician Surface, G4 + G5)
delivered the inbound half: a real SMART EHR launch with OIDC identity bridging (fail-closed,
tenant-isolated, audited, no separate login, EHR-bounded session), a clinician-facing
chart-context panel over the immutable snapshot, an embedded review surface, and validated
Epic/Athena marketplace manifests. Both run behind injected transport/verifier/clock seams,
validated against vendor-emulating fakes; live Epic/Athena sandbox + marketplace certification
(and the RS256/JWKS id_token verifier) are the remaining steps for those gaps. Phases 9–11
(billing/coding, specialty breadth, retention/purge) remain open.
