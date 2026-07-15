# domains/coding — Billing & Coding Intelligence (Phase 9, closes G1)

Deterministic revenue-integrity module. Given the canonical chart context (the immutable
`ContextSnapshot` the protocol engine already reasoned over), the documented problem list, and
the diagnoses already on the encounter, it flags coding gaps as **human-confirmed suggestions in
a review queue** — never auto-applied to a claim.

## What it detects (all deterministic, all evidence-linked)
- **documented_uncoded** — an active problem-list condition whose ICD-10 code is missing from the
  encounter's diagnosis set.
- **hcc_gap** — a risk-adjustable condition *suspected* from objective lab evidence at/over a
  diagnostic threshold, yet neither documented nor coded (e.g. A1c ≥ 6.5% ⇒ suspected diabetes;
  eGFR < 60 ⇒ suspected CKD stage 3+). Always flagged `requires_provider_confirmation`.
- **specificity_upgrade** — an unspecified code on the encounter the chart can sharpen (e.g.
  unspecified CKD `N18.9` + a staging eGFR; diabetes without complications `E11.9` + CKD evidence).

## Governance (same posture as Phase 6)
- **No auto-apply.** Suggestions are created `PENDING`. Only `confirm_suggestion` (human,
  actor-attributed) advances one, and only a `CONFIRMED` suggestion can be `export`-ed. There is
  no path that applies a suggestion without a human.
- **Anti-upcoding guardrails.** No evidence ⇒ no suggestion (asserted in `core.analyze`);
  conservative thresholds (nothing below the diabetes A1c threshold or at eGFR ≥ 60).
- **Auditable + governed.** Every decision writes a hash-chained `AuditEvent` (actor + evidence)
  and publishes a domain event; confirmations/rejections feed the Phase 6 analytics loop as
  `coding` feedback (approve/override), so acceptance and override rates are tracked.

## Files
- `catalog.py` — the deterministic clinical content (ICD-10 codes, HCC tags, eGFR→CKD staging,
  A1c threshold). Seed/illustrative; extended via the governed authoring path (Phase 10).
- `core.py` — pure, Django-free detectors + `analyze`.
- `models.py` — `CodingSuggestionRecord` (RLS-isolated review queue).
- `services.py` — the only public entry point (analyze / confirm / reject / export / list).

## Public interface
`domains.coding.services`: `analyze_encounter`, `analyze_from_snapshot`, `confirm_suggestion`,
`reject_suggestion`, `export_suggestion`, `list_suggestions`.
