"""Domain events published by the Refills module (Phase 4; spec §6.3).

Cross-module communication happens through explicit domain events (spec §7.5) — never direct
ORM reach-across. Publish via ``core.outbox.publish_event`` inside the same DB transaction.

Events (defined on ``clinara_shared_types.EventType``):
  * ``RefillRequestReceived`` — an inbound refill request was stored.
  * ``RefillEvaluated``       — the deterministic refill engine produced a decision.
  * ``RefillDecided``         — a human (or the low-risk allowlist) finalised the outcome.
"""
