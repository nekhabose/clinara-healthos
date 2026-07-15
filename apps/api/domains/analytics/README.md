# Analytics & Personalization (Phase 6)

Closes the loop (spec §12, §6.4.3): accumulated feedback becomes governed dashboards and
**approval-gated** personalization that can **never weaken safety**.

- `core.py` — **pure, Django-free**: edit-diff, feedback aggregation, preference derivation,
  the `assert_preference_safe` guard (safety-protected fields can never be personalized), and
  privacy controls (`suppress_small_cells`, `deidentify`).
- `models.py` — `PractitionerPreference` (inactive until approved),
  `ConfigurationRecommendation` (pending → approved/rejected → deployed), `AnalyticsSnapshot`.
- `services.py` — dashboards, `derive_preferences` (→ *pending* recommendation),
  `approve_recommendation` (the only path to effect), and `cross_tenant_report`
  (de-identified + small-cell-suppressed).

## Guarantees
- **Recommendation engine, not an actuator** — recommendations are inert until a human
  approves them; no path applies a change autonomously.
- **Preferences provably cannot weaken safety** — only allowlisted low-risk fields; any
  safety-protected field is a hard error.
- **Cross-tenant learning is de-identified** and small cells are suppressed (spec §12.5, §4.2).

## Boundary rules (spec §7.4)
- This module owns its own domain models. Other modules must not import them directly.
- Cross-module access goes through `services.py` only; domain events via the outbox.
- No clinical decision logic in controllers/serializers.
- Tenant customization is data-driven — never code branches.
