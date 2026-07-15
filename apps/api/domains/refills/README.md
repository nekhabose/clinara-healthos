# Refills — Prescription & Refill Intelligence (Phase 4)

The second governed clinical workflow (spec §6.3), on the same rails as Results Intelligence.
A refill decision is produced by **deterministic logic — never an LLM** (`core.evaluate_refill`):
an ordered cascade that puts safety exclusions first (missing identity, allergy,
contraindication, interaction, discontinuation, dose mismatch, controlled substances) and
convenience last. Every decision records the exact `clinical_factors_used`.

## Guarantees
- **No medication change is ever LLM-generated** — the model only drafts response wording.
- **Missing medication identity blocks automation**; unknown RxNorm codes are not guessed.
- **Controlled substances** follow a separate, non-overridable human path — client/clinician
  config cannot loosen it.
- **Auto-approve is opt-in** to an explicitly approved low-risk allowlist; everything else
  routes to a human.

## Boundary rules (spec §7.4)
- This module owns its own domain models. Other modules must not import them directly.
- Cross-module access goes through `services.py` only; domain events via the outbox.
- No clinical decision logic in controllers/serializers.
- Tenant customization is data-driven — never code branches.
