"""Refills persistence (plan Phase 4 data-model deltas).

Tenant-scoped canonical medication data + the reviewable refill workflow. Every refill
decision stores the exact factors it used so it is fully traceable (spec §6.3.5); the
deterministic decision + human actions are audited by the service layer.
"""
from __future__ import annotations

from django.db import models

from core.models import TenantScopedModel


class MedicationStatement(TenantScopedModel):
    """A patient's current medication (spec §8.2 medication data)."""

    patient_external_id = models.CharField(max_length=128, db_index=True)
    rxnorm = models.CharField(max_length=32)
    name = models.CharField(max_length=200)
    med_class = models.CharField(max_length=32)
    schedule = models.CharField(max_length=8, default="none")
    prescribed_dose = models.CharField(max_length=64, blank=True, default="")
    active = models.BooleanField(default=True)
    discontinued = models.BooleanField(default=False)
    days_supply = models.PositiveIntegerField(null=True, blank=True)
    last_fill_days_ago = models.IntegerField(null=True, blank=True)

    class Meta:
        indexes = [models.Index(fields=["tenant_id", "patient_external_id", "rxnorm"])]
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"medstatement:{self.name}"


class AllergyIntolerance(TenantScopedModel):
    patient_external_id = models.CharField(max_length=128, db_index=True)
    substance = models.CharField(max_length=128)  # medication name or class

    class Meta:
        ordering = ["substance"]

    def __str__(self) -> str:
        return f"allergy:{self.substance}"


class ClientMonitoringPolicy(TenantScopedModel):
    """Client-configurable monitoring / auto-approve policy per therapeutic class (spec §6.3.5)."""

    med_class = models.CharField(max_length=32)
    requires_monitoring_labs = models.BooleanField(default=False)
    visit_required_within_days = models.PositiveIntegerField(null=True, blank=True)
    auto_approve = models.BooleanField(default=False)  # opt-in low-risk automation

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["tenant_id", "med_class"], name="uq_monitoring_policy_class"
            )
        ]

    def __str__(self) -> str:
        return f"policy:{self.med_class}"


class RefillStatus(models.TextChoices):
    PENDING_REVIEW = "pending_review", "Pending review"
    AUTO_APPROVED = "auto_approved", "Auto-approved"
    APPROVED = "approved", "Approved"
    REJECTED = "rejected", "Rejected"
    ESCALATED = "escalated", "Escalated"
    ROUTED = "routed", "Routed"
    CLOSED = "closed", "Closed"


class RefillWorkflow(TenantScopedModel):
    """The reviewable refill unit surfaced to a nurse/prescriber (spec §6.3.4)."""

    workflow_type = models.CharField(max_length=32, default="refill")
    correlation_id = models.CharField(max_length=64, db_index=True)
    patient_external_id = models.CharField(max_length=128)
    rxnorm = models.CharField(max_length=32)
    medication_name = models.CharField(max_length=200, blank=True, default="")
    requested_dose = models.CharField(max_length=64, blank=True, default="")
    outcome = models.CharField(max_length=40)
    controlled_substance = models.BooleanField(default=False)
    automation_allowed = models.BooleanField(default=False)
    status = models.CharField(
        max_length=16, choices=RefillStatus.choices,
        default=RefillStatus.PENDING_REVIEW, db_index=True,
    )

    class Meta:
        indexes = [models.Index(fields=["tenant_id", "status", "outcome"])]
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"refill:{self.medication_name}:{self.outcome}"


class RefillEvaluationRecord(TenantScopedModel):
    """The stored deterministic refill decision + exact factors used (spec §6.3.5)."""

    workflow = models.ForeignKey(
        RefillWorkflow, on_delete=models.CASCADE, related_name="evaluations"
    )
    outcome = models.CharField(max_length=40)
    reason_codes = models.JSONField(default=list)
    required_actions = models.JSONField(default=list)
    clinical_factors_used = models.JSONField(default=list)
    decision = models.JSONField()

    def __str__(self) -> str:
        return f"refill_eval:{self.outcome}"


class RefillReviewAction(models.TextChoices):
    APPROVE = "approve", "Approve"
    REJECT = "reject", "Reject"
    ROUTE = "route", "Route"
    ESCALATE = "escalate", "Escalate"


class RefillReview(TenantScopedModel):
    workflow = models.ForeignKey(
        RefillWorkflow, on_delete=models.CASCADE, related_name="reviews"
    )
    action = models.CharField(max_length=16, choices=RefillReviewAction.choices)
    actor = models.CharField(max_length=128)
    reason = models.TextField(blank=True, default="")

    class Meta:
        ordering = ["created_at"]

    def __str__(self) -> str:
        return f"{self.action} by {self.actor}"
