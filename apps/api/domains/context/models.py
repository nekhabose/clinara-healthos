"""Context persistence (plan Phase 1 — immutable, hashed snapshot record, spec §8.3).

The snapshot's facts + provenance are stored verbatim alongside a content hash so a
workflow can be replayed against the exact inputs that produced its decision (plan §1.1).
The row is written once and never updated.
"""
from __future__ import annotations

from django.db import models

from core.models import TenantScopedModel


class ContextSnapshotRecord(TenantScopedModel):
    workflow_id = models.UUIDField(db_index=True)
    patient_external_id = models.CharField(max_length=128)
    snapshot_hash = models.CharField(max_length=64, db_index=True)
    facts = models.JSONField()
    provenance = models.JSONField()
    builder_version = models.CharField(max_length=32)

    class Meta:
        indexes = [models.Index(fields=["tenant_id", "workflow_id"])]

    def __str__(self) -> str:
        return f"snapshot:{self.snapshot_hash[:12]}"
