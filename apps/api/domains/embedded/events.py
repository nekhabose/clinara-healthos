"""Domain events published by the EHR-Embedded Surface module.

Cross-module communication happens through explicit domain events (spec §7.5) — never direct
ORM reach-across. Publish via ``core.outbox.publish_event`` inside the same DB transaction.

Emitted here (see ``services``):
  * ``EhrLaunched``      — a clinician SMART launch was bridged to a Clinara session.
  * ``EhrLaunchDenied``  — a launch could not be bridged (no identity link) and was refused.
"""
