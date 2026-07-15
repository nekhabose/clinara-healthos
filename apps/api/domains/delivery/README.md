# Delivery — EHR Write-Back & Patient Messaging (Phase 3)

Governed, **idempotent** write-back (spec §6.7, workstream 4). `queue_write_back` is keyed
by (workflow, channel) so a duplicate approved event never creates a second EHR task or
portal message. `deliver` records a `DeliveryAttempt`, confirms via an injectable
`EhrClient`, and emits `DeliverySucceeded` / `DeliveryFailed` — a failure is data on the ops
board, never a silent drop.

## Boundary rules (spec §7.4)
- This module owns its own domain models. Other modules must not import them directly.
- Cross-module access goes through `services.py` (the public service interface) only.
- Domain events are explicit and published via the transactional outbox.
- No clinical decision logic in controllers/serializers.
- Tenant customization is data-driven — never code branches.
