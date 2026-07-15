# Feedback — the learning loop's raw signal (Phase 6)

Structured capture of what clinicians do with generated outputs — approve / edit / override /
escalate — with per-edit **edit-difference** analysis (spec §12), plus patient responses and
protocol feedback. This domain only **records**; it never changes behaviour. Every capture is
audited and emits `FeedbackCaptured`.

## Boundary rules (spec §7.4)
- This module owns its own domain models. Other modules must not import them directly.
- Cross-module access goes through `services.py` only; domain events via the outbox.
- No clinical decision logic in controllers/serializers.
- Tenant customization is data-driven — never code branches.
