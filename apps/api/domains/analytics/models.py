"""Analytics & personalization persistence (plan Phase 6 data-model deltas).

`PractitionerPreference` and `ConfigurationRecommendation` are the personalization outputs —
**inert data** until a human approves them. A recommendation can never take effect on its
own: `status` moves to `approved` only through the governed service, and to `deployed` only
after it routes through the Phase 2 deployment pipeline. This is the structural guarantee
that personalization is a recommendation engine, not an actuator (plan Phase 6 key decision).
"""
from __future__ import annotations

from django.db import models

from core.models import TenantScopedModel


class PractitionerPreference(TenantScopedModel):
    """A derived, low-risk preference signal (spec §6.4.3). Never touches safety fields."""

    practitioner = models.CharField(max_length=128, db_index=True)
    adjustments = models.JSONField(default=dict)   # allowlisted low-risk fields only
    derived_from = models.PositiveIntegerField(default=0)
    active = models.BooleanField(default=False)    # applied only after governed approval

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["tenant_id", "practitioner"], name="uq_preference_practitioner"
            )
        ]
        ordering = ["practitioner"]

    def __str__(self) -> str:
        return f"preference:{self.practitioner}"


class RecommendationStatus(models.TextChoices):
    PENDING = "pending", "Pending approval"
    APPROVED = "approved", "Approved"
    REJECTED = "rejected", "Rejected"
    DEPLOYED = "deployed", "Deployed"


class ConfigurationRecommendation(TenantScopedModel):
    """A recommended config change (plan Phase 6). Inert until approved + deployed."""

    kind = models.CharField(max_length=48)
    target = models.CharField(max_length=128)
    proposal = models.JSONField(default=dict)
    rationale = models.TextField(blank=True, default="")
    supporting_observations = models.PositiveIntegerField(default=0)
    status = models.CharField(
        max_length=12, choices=RecommendationStatus.choices,
        default=RecommendationStatus.PENDING, db_index=True,
    )
    approved_by = models.CharField(max_length=128, blank=True, default="")
    deployment_ref = models.CharField(max_length=128, blank=True, default="")

    class Meta:
        indexes = [models.Index(fields=["tenant_id", "status", "kind"])]
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"recommendation:{self.kind}[{self.status}]"


class AnalyticsSnapshot(TenantScopedModel):
    """A materialized dashboard snapshot (executive / clinical / operations) — spec §12."""

    scope = models.CharField(max_length=48, db_index=True)
    metrics = models.JSONField(default=dict)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"analytics:{self.scope}"
