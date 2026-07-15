"""Domain events published by the Continuity module.

A completed DR reconciliation publishes ``DisasterRecoveryReconciled`` so operators and the
release gate see the drill outcome. Replay of unpublished events is executed by the existing
outbox relay; workflow reconciliation by the durable saga runner.
"""
