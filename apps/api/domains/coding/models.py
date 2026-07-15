"""Coding-suggestion persistence (plan Phase 9 — closes G1).

A ``CodingSuggestionRecord`` is one revenue-integrity suggestion in the review queue. It is
**inert by construction**: created ``PENDING`` and only a human action (confirm/reject) moves
it. Nothing here is ever auto-applied to a claim — the record captures the deterministic
evidence and the human decision so the whole lifecycle is auditable (spec §1.1; same
governance posture as the Phase 6 analytics loop). Suggestions are tenant-scoped and
RLS-isolated.
"""
from __future__ import annotations

from django.db import models

from core.models import TenantScopedModel


class SuggestionStatus(models.TextChoices):
    PENDING = "pending", "Pending review"
    CONFIRMED = "confirmed", "Confirmed by clinician"
    REJECTED = "rejected", "Rejected"
    EXPORTED = "exported", "Exported to coding/claim"


class CodingSuggestionRecord(TenantScopedModel):
    # Chart context this rode on (the immutable snapshot + workflow it was derived from).
    workflow_id = models.UUIDField(null=True, blank=True, db_index=True)
    patient_external_id = models.CharField(max_length=128)
    encounter_id = models.CharField(max_length=128, blank=True, default="")
    snapshot_hash = models.CharField(max_length=64, blank=True, default="")

    suggestion_type = models.CharField(max_length=32)
    icd10_code = models.CharField(max_length=16)
    description = models.CharField(max_length=256)
    hcc = models.CharField(max_length=64, blank=True, default="")
    supersedes_code = models.CharField(max_length=16, blank=True, default="")
    requires_provider_confirmation = models.BooleanField(default=True)

    rationale = models.TextField(blank=True, default="")
    evidence = models.JSONField(default=list)  # deterministic, evidence-linked (never empty)
    # Stable identity of the underlying gap; idempotent re-analysis updates in place.
    dedup_key = models.CharField(max_length=128, db_index=True)

    status = models.CharField(
        max_length=16, choices=SuggestionStatus.choices,
        default=SuggestionStatus.PENDING, db_index=True,
    )
    decided_by = models.CharField(max_length=128, blank=True, default="")
    decided_at = models.DateTimeField(null=True, blank=True)
    decision_reason = models.TextField(blank=True, default="")

    class Meta:
        indexes = [
            models.Index(fields=["tenant_id", "status"]),
            models.Index(fields=["tenant_id", "workflow_id"]),
        ]
        # One live suggestion per (tenant, patient, encounter, gap) — keeps re-analysis
        # idempotent instead of piling duplicates into the queue.
        constraints = [
            models.UniqueConstraint(
                fields=["tenant_id", "patient_external_id", "encounter_id", "dedup_key"],
                name="uq_coding_suggestion_per_gap",
            )
        ]
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"coding:{self.suggestion_type}:{self.icd10_code}:{self.status}"
