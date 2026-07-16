# Messages — Patient Message Intelligence (Phase 5)

Classifies, extracts, summarizes, prioritizes, and routes inbound patient messages
(spec §6.2) — the most LLM-dependent module, built last on the battle-tested deterministic
scaffolding. The governing invariant:

> A **deterministic red-flag detector is the safety floor.** The LLM classifier may only
> *raise* concern above it — it can never lower urgency below the deterministic result, and
> model confidence alone never sets urgency.

- `core.py` — **pure, Django-free** triage: `detect_red_flags` (multilingual, runs on the
  verbatim message), a swappable `Classifier` (the LLM role; default is a deterministic
  keyword classifier), `assign_urgency` (red-flag floor ∨ category baseline), `route`, and
  the `validate_identity` cross-patient contamination guard.
- `models.py` — `PatientMessage` (stored verbatim), `MessageClassificationRecord`,
  `MessageReview` (tenant-scoped; RLS).
- `services.py` — store → red-flag scan → classify → deterministic urgency → contamination
  guard → route → auto-draft (approved non-clinical categories only). Audited + events.

## Guarantees
- Emergencies escalate on the red-flag scan **regardless of model output**.
- High-risk (clinical) categories are **never fully auto-resolved**.
- Cross-patient context contamination is **blocked before chart reasoning**.
- Prompt-injection in patient text cannot suppress a red flag or seize routing/urgency.

## Boundary rules (spec §7.4)
- This module owns its own domain models. Other modules must not import them directly.
- Cross-module access goes through `services.py` only; domain events via the outbox.
- No clinical decision logic in controllers/serializers.
- Tenant customization is data-driven — never code branches.
