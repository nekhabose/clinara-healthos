"""Patient message persistence (plan Phase 5 data-model deltas).

The inbound patient ``PatientMessage`` is stored VERBATIM (spec §6.2 — preserve the original
message) before any processing. The deterministic red-flag evaluation, the classification,
and the routing decision are each recorded so triage is fully explainable and the red-flag
floor is auditable independent of the model.
"""
from __future__ import annotations

from django.db import models

from core.models import TenantScopedModel


class MessageStatus(models.TextChoices):
    RECEIVED = "received", "Received"
    TRIAGED = "triaged", "Triaged"
    ESCALATED = "escalated", "Escalated"
    RESOLVED = "resolved", "Resolved"
    ROUTED = "routed", "Routed"
    BLOCKED = "blocked", "Blocked (identity)"


class PatientMessage(TenantScopedModel):
    """An inbound patient-portal message, stored verbatim (spec §6.2)."""

    correlation_id = models.CharField(max_length=64, db_index=True)
    patient_external_id = models.CharField(max_length=128, db_index=True)
    channel = models.CharField(max_length=48, default="patient_portal")
    original_text = models.TextField()          # verbatim; never mutated
    language = models.CharField(max_length=8, default="en")

    category = models.CharField(max_length=32, blank=True, default="")
    urgency = models.CharField(max_length=32, blank=True, default="")
    red_flags = models.JSONField(default=list)
    reason_codes = models.JSONField(default=list)
    destination = models.CharField(max_length=32, blank=True, default="")
    auto_resolvable = models.BooleanField(default=False)
    draft_response = models.TextField(blank=True, default="")
    status = models.CharField(
        max_length=16, choices=MessageStatus.choices,
        default=MessageStatus.RECEIVED, db_index=True,
    )

    class Meta:
        indexes = [models.Index(fields=["tenant_id", "status", "urgency"])]
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"message:{self.category or 'unclassified'}:{self.urgency or '-'}"


class MessageClassificationRecord(TenantScopedModel):
    """The red-flag + classification + urgency detail (explainable triage)."""

    message = models.ForeignKey(
        PatientMessage, on_delete=models.CASCADE, related_name="classifications"
    )
    category = models.CharField(max_length=32)
    confidence = models.FloatField(default=0.0)
    urgency = models.CharField(max_length=32)
    red_flags = models.JSONField(default=list)
    symptoms = models.JSONField(default=list)
    medications = models.JSONField(default=list)
    summary = models.TextField(blank=True, default="")

    def __str__(self) -> str:
        return f"classification:{self.category}:{self.urgency}"


class MessageReviewAction(models.TextChoices):
    RESPOND = "respond", "Respond"
    ROUTE = "route", "Route"
    ESCALATE = "escalate", "Escalate"
    RESOLVE = "resolve", "Resolve"


class MessageReview(TenantScopedModel):
    message = models.ForeignKey(
        PatientMessage, on_delete=models.CASCADE, related_name="reviews"
    )
    action = models.CharField(max_length=16, choices=MessageReviewAction.choices)
    actor = models.CharField(max_length=128)
    response_text = models.TextField(blank=True, default="")
    reason = models.TextField(blank=True, default="")

    class Meta:
        ordering = ["created_at"]

    def __str__(self) -> str:
        return f"{self.action} by {self.actor}"
