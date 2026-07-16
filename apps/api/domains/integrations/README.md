# Integrations — Hardened EHR Gateway (Phase 3)

The production front door for real HL7/FHIR traffic (spec §6.7). It resolves the tenant +
interface, stores raw payloads, rate-limits abusive sources, guards malformed payloads,
dedupes duplicates, normalizes timestamps, and publishes canonical events — with **zero
silent loss**: anything unprocessable is dead-lettered (visible, replayable), never dropped.

- `gateway.py` — `receive_fhir` / `receive_hl7` / `replay_dead_letter`. Malformed →
  `DeadLetterEvent`; rate-limited → recorded; duplicates → no-op. Idempotent replay.
- `monitoring.py` — `integration_health`, `dashboard`, and `scan_silent_gaps` (detects the
  *absence* of expected traffic and raises a critical alert — spec §12.3).
- Adapters live in `clinara_integration_sdk` (HL7 v2 parser, token bucket, gap detector) —
  vendor quirks never leak into clinical logic.
- Tenant-specific mappings (`terminology.IntegrationMapping`) are honoured end-to-end.

## Boundary rules (spec §7.4)
- This module owns its own domain models. Other modules must not import them directly.
- Cross-module access goes through `services.py` (the public service interface) only.
- Domain events are explicit and published via the transactional outbox.
- No clinical decision logic in controllers/serializers.
- Tenant customization is data-driven — never code branches.
