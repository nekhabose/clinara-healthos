"""Operations persistence (plan Phase 1 — the visible failure/unmapped queue).

Anything that cannot be processed is parked here rather than dropped (plan §1.1 invariant
2). Phase 3 adds the full dead-letter/replay tooling on top of this.
"""
from __future__ import annotations

from django.db import models

from core.models import TenantScopedModel


class QueueKind(models.TextChoices):
    UNMAPPED_CODE = "unmapped_code", "Unmapped code"
    UNSUPPORTED_UNIT = "unsupported_unit", "Unsupported unit"
    FAILED_EVENT = "failed_event", "Failed event"
    NO_PATIENT_MATCH = "no_patient_match", "No patient match"


class QueueStatus(models.TextChoices):
    OPEN = "open", "Open"
    RESOLVED = "resolved", "Resolved"


class OperationsQueueItem(TenantScopedModel):
    kind = models.CharField(max_length=24, choices=QueueKind.choices, db_index=True)
    reference = models.CharField(max_length=200, blank=True, default="")  # e.g. idempotency key
    detail = models.CharField(max_length=255, blank=True, default="")
    payload = models.JSONField(default=dict)
    status = models.CharField(
        max_length=16, choices=QueueStatus.choices, default=QueueStatus.OPEN, db_index=True
    )

    class Meta:
        indexes = [models.Index(fields=["tenant_id", "kind", "status"])]
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.kind}:{self.reference}[{self.status}]"
