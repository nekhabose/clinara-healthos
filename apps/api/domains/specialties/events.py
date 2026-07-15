"""Domain events published by Specialty Protocol Breadth (plan Phase 10 — closes G6).

Publish via ``core.outbox.publish_event`` inside the same DB transaction as the write.
Emitted here (see ``services``):

  * ``SpecialtyThresholdUpdated`` — a practice overrode a pack threshold parameter (actor +
    before/after value). The override is validated (pack still passes its activation gate)
    before it is stored, so a customization can never weaken safety or break required tests.
  * ``SpecialtyThresholdReset``   — a practice cleared its overrides back to pack defaults.
"""
