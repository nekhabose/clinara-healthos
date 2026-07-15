"""Domain events published by the Kill Switch module.

Engaging or releasing a kill switch is an operationally significant, auditable act — it is
published to the outbox so downstream monitoring/eligibility react and the action is never
silent (spec §11.4, §12.3 "critical workflow automation anomaly").
"""
