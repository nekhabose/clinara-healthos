"""Workflow persistence (plan Phase 1 data-model deltas).

A ``WorkflowInstance`` is the reviewable unit surfaced to a clinician. It aggregates the
deterministic decision, the generated + validated communication, and the human actions
taken on it. Every mutating action is audited by the service layer.
"""
from __future__ import annotations

from django.db import models

from core.models import TenantScopedModel


class WorkflowStatus(models.TextChoices):
    PENDING_REVIEW = "pending_review", "Pending review"
    APPROVED = "approved", "Approved"
    EDITED = "edited", "Edited & approved"
    OVERRIDDEN = "overridden", "Overridden"
    ESCALATED = "escalated", "Escalated"
    CLOSED = "closed", "Closed"
    BLOCKED = "blocked", "Blocked (unsupported)"
    SUPPRESSED = "suppressed", "Automation suppressed"


class WorkflowInstance(TenantScopedModel):
    workflow_type = models.CharField(max_length=32, default="results")
    correlation_id = models.CharField(max_length=64, db_index=True)
    patient_external_id = models.CharField(max_length=128)
    observation_id = models.UUIDField(null=True, blank=True)
    marker = models.CharField(max_length=64)
    classification = models.CharField(max_length=48)
    priority = models.CharField(max_length=16)
    automation_status = models.CharField(max_length=32)
    status = models.CharField(
        max_length=20, choices=WorkflowStatus.choices,
        default=WorkflowStatus.PENDING_REVIEW, db_index=True,
    )

    class Meta:
        indexes = [models.Index(fields=["tenant_id", "status", "priority"])]
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"workflow:{self.marker}:{self.status}"


class ProtocolEvaluationRecord(TenantScopedModel):
    """The stored deterministic decision + replay trace (spec §6.1.5)."""

    workflow = models.ForeignKey(
        WorkflowInstance, on_delete=models.CASCADE, related_name="evaluations"
    )
    marker = models.CharField(max_length=64)
    matched_rule_id = models.CharField(max_length=64, blank=True, default="")
    matched_rule_version = models.PositiveIntegerField(null=True, blank=True)
    critical_triggered = models.BooleanField(default=False)
    decision = models.JSONField()   # ResultDecision.model_dump()
    trace = models.JSONField()      # EvaluationTrace.model_dump()

    def __str__(self) -> str:
        return f"evaluation:{self.marker}"


class GeneratedCommunication(TenantScopedModel):
    workflow = models.ForeignKey(
        WorkflowInstance, on_delete=models.CASCADE, related_name="communications"
    )
    template_key = models.CharField(max_length=96, blank=True, default="")
    patient_message = models.TextField(blank=True, default="")
    clinician_summary = models.TextField(blank=True, default="")
    validation_passed = models.BooleanField(default=False)
    validation_failures = models.JSONField(default=list)
    used_fallback = models.BooleanField(default=False)

    def __str__(self) -> str:
        return f"communication:{self.template_key or 'fallback'}"


class ReviewAction(models.TextChoices):
    APPROVE = "approve", "Approve"
    EDIT = "edit", "Edit & approve"
    OVERRIDE = "override", "Override"
    ESCALATE = "escalate", "Escalate"
    REJECT = "reject", "Reject"
    CLOSE = "close", "Close"


class HumanReview(TenantScopedModel):
    workflow = models.ForeignKey(
        WorkflowInstance, on_delete=models.CASCADE, related_name="reviews"
    )
    action = models.CharField(max_length=16, choices=ReviewAction.choices)
    actor = models.CharField(max_length=128)
    edited_message = models.TextField(blank=True, default="")
    reason = models.TextField(blank=True, default="")

    class Meta:
        ordering = ["created_at"]

    def __str__(self) -> str:
        return f"{self.action} by {self.actor}"


class Escalation(TenantScopedModel):
    workflow = models.ForeignKey(
        WorkflowInstance, on_delete=models.CASCADE, related_name="escalations"
    )
    reason = models.CharField(max_length=255)

    def __str__(self) -> str:
        return f"escalation:{self.reason}"
