"""Domain events published by the Data Lifecycle module (plan Phase 11 — closes G7).

Publish via ``core.outbox.publish_event`` inside the same DB transaction as the write.
Emitted here (see ``services``):

  * ``RetentionPolicyUpdated`` — a practice changed a per-category retention window.
  * ``DataPurged``            — a scheduled minimization/purge run completed (per-category
                                counts + the cutoff each was measured against).
  * ``TenantDataPurged``      — a BAA-termination hard-purge completed; a tamper-evident
                                certificate of destruction was issued.

Every purge is also recorded in the immutable, hash-chained audit trail with the reserved
``AuditAction.DATA_PURGE`` action. The audit trail itself is NEVER a purge target.
"""
