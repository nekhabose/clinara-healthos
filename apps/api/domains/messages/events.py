"""Domain events published by the Messages module (Phase 5; spec §6.2).

Cross-module communication happens through explicit domain events (spec §7.5). Publish via
``core.outbox.publish_event`` inside the same DB transaction.

Events (defined on ``clinara_shared_types.EventType``):
  * ``PatientMessageReceived`` — an inbound patient message was stored (verbatim).
  * ``MessageClassified``      — red-flag + classification + deterministic urgency produced.
  * ``MessageRouted``          — the message was routed / escalated to its destination.
"""
