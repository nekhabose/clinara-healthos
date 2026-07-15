"""Domain events published by the Protocols module (Clinical Rule Studio, plan Phase 2).

Cross-module communication happens through explicit domain events (spec §7.5) — never
direct ORM reach-across. Publish via ``core.outbox.publish_event`` inside the same DB
transaction as the state change.

Events emitted by ``domains.protocols.services``:

  * ``ProtocolSimulated``  — a version was simulated against scenarios (spec §6.5.6).
  * ``ProtocolApproved``   — a version reached dual clinical + engineering approval.
  * ``ProtocolDeployed``   — a version was released (shadow / progressive / full, §6.5.8).
  * ``ProtocolRolledBack`` — a deployment was reverted to its safe version.

All four are defined on ``clinara_shared_types.EventType``.
"""
