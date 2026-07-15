"""DR drill persistence (GA hardening — spec §15).

Each restore drill (quarterly, per spec §15) records its reconciliation outcome so the DR
history is auditable and the release gate can confirm a recent passing drill. Platform-level,
not tenant PHI.
"""
from __future__ import annotations

import uuid

from django.db import models


class DrillOutcome(models.TextChoices):
    PASSED = "passed", "Passed"
    FAILED = "failed", "Failed"


class DisasterRecoveryDrill(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    label = models.CharField(max_length=120)
    outcome = models.CharField(max_length=8, choices=DrillOutcome.choices, db_index=True)
    rpo_met = models.BooleanField()
    rto_met = models.BooleanField()
    data_loss_seconds = models.FloatField()
    downtime_seconds = models.FloatField()
    replay_count = models.PositiveIntegerField(default=0)
    stranded_count = models.PositiveIntegerField(default=0)
    notes = models.JSONField(default=list)
    ran_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-ran_at"]

    def __str__(self) -> str:
        return f"{self.label}[{self.outcome}]"
