"""Feedback persistence (plan Phase 6 data-model deltas — the learning loop's raw signal).

Structured capture of what clinicians do with generated outputs (approve / edit / override /
escalate), what patients respond, and protocol feedback. Edit differences are stored so
personalization can be derived later — but this domain only *records*; it never acts.
"""
from __future__ import annotations

from django.db import models

from core.models import TenantScopedModel


class ClinicianFeedback(TenantScopedModel):
    """One clinician action on a generated output, with its edit difference if any."""

    workflow_type = models.CharField(max_length=32)  # results | refill | message
    workflow_id = models.UUIDField(db_index=True)
    practitioner = models.CharField(max_length=128, db_index=True)
    action = models.CharField(max_length=16)          # approve | edit | override | escalate
    protocol_key = models.CharField(max_length=96, blank=True, default="")
    specialty = models.CharField(max_length=64, blank=True, default="")
    original_text = models.TextField(blank=True, default="")
    edited_text = models.TextField(blank=True, default="")
    edit_difference = models.JSONField(default=dict)
    reason = models.TextField(blank=True, default="")

    class Meta:
        indexes = [models.Index(fields=["tenant_id", "workflow_type", "action"])]
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"feedback:{self.workflow_type}:{self.action}"


class PatientResponse(TenantScopedModel):
    workflow_type = models.CharField(max_length=32)
    workflow_id = models.UUIDField(db_index=True)
    responded = models.BooleanField(default=False)
    sentiment = models.CharField(max_length=16, blank=True, default="")

    def __str__(self) -> str:
        return f"patient_response:{self.workflow_type}"


class ProtocolFeedback(TenantScopedModel):
    protocol_key = models.CharField(max_length=96, db_index=True)
    signal = models.CharField(max_length=64)          # e.g. "override_spike"
    detail = models.JSONField(default=dict)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"protocol_feedback:{self.protocol_key}:{self.signal}"
