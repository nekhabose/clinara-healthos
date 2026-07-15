"""Delivery persistence (plan Phase 3, workstream 4 — EHR write-back & patient messaging).

An ``OutboundMessage`` is a governed, idempotent unit of write-back: a Task/inbox item to
the EHR or a patient-portal message. It is only ever created for an approved workflow, and
its ``idempotency_key`` guarantees a duplicate inbound event (or a retried delivery) never
produces a duplicate task or message (spec §6.7.6, plan Phase 3 exit gate). Each physical
send is a ``DeliveryAttempt`` recording success/failure for confirmation + retry.
"""
from __future__ import annotations

from django.db import models

from core.models import TenantScopedModel


class OutboundChannel(models.TextChoices):
    EHR_TASK = "ehr_task", "EHR task/inbox"
    PATIENT_PORTAL = "patient_portal", "Patient portal message"


class OutboundStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    DELIVERED = "delivered", "Delivered"
    FAILED = "failed", "Failed"


class OutboundMessage(TenantScopedModel):
    channel = models.CharField(max_length=20, choices=OutboundChannel.choices)
    workflow_id = models.UUIDField(null=True, blank=True, db_index=True)
    target = models.CharField(max_length=200)          # EHR task recipient / patient portal id
    subject = models.CharField(max_length=200, blank=True, default="")
    body = models.TextField(blank=True, default="")
    idempotency_key = models.CharField(max_length=200, unique=True)
    status = models.CharField(
        max_length=12, choices=OutboundStatus.choices,
        default=OutboundStatus.PENDING, db_index=True,
    )
    external_id = models.CharField(max_length=200, blank=True, default="")  # id returned by EHR

    class Meta:
        indexes = [models.Index(fields=["tenant_id", "status", "channel"])]
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"outbound:{self.channel}[{self.status}]"


class DeliveryAttempt(TenantScopedModel):
    message = models.ForeignKey(
        OutboundMessage, on_delete=models.CASCADE, related_name="attempts"
    )
    succeeded = models.BooleanField(default=False)
    detail = models.CharField(max_length=255, blank=True, default="")

    class Meta:
        ordering = ["created_at"]

    def __str__(self) -> str:
        return f"attempt:{'ok' if self.succeeded else 'fail'}"
