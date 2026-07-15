# Delivery

EHR write-back, patient-portal messaging, delivery confirmation (Phase 3).

## Boundary rules (spec §7.4)
- This module owns its own domain models. Other modules must not import them directly.
- Cross-module access goes through `services.py` (the public service interface) only.
- Domain events are explicit and published via the transactional outbox.
- No clinical decision logic in controllers/serializers.
- Tenant customization is data-driven — never code branches.
