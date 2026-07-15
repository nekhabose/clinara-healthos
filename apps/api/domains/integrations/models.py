"""Integrations persistence (plan Phase 1 — sandbox ingestion).

Phase 1 stores the raw inbound payload BEFORE parsing and derives a stable idempotency key
so duplicate deliveries never double-process (spec §6.7.6). The full hardened gateway
(HL7/FHIR adapters, dead-letter, replay) arrives in Phase 3.
"""
from __future__ import annotations

from django.db import models

from core.models import TenantScopedModel


class InboundStatus(models.TextChoices):
    RECEIVED = "received", "Received"
    PROCESSED = "processed", "Processed"
    FAILED = "failed", "Failed"


class InboundMessage(TenantScopedModel):
    """Raw payload store — the durable record that nothing was silently dropped."""

    source = models.CharField(max_length=64)                 # e.g. "fhir-sandbox"
    message_type = models.CharField(max_length=64)           # e.g. "Observation"
    idempotency_key = models.CharField(max_length=200, unique=True)
    raw_payload = models.JSONField()
    status = models.CharField(
        max_length=16, choices=InboundStatus.choices, default=InboundStatus.RECEIVED, db_index=True
    )
    error = models.TextField(blank=True, default="")

    class Meta:
        indexes = [models.Index(fields=["tenant_id", "status", "created_at"])]
        ordering = ["created_at"]

    def __str__(self) -> str:
        return f"{self.message_type}:{self.idempotency_key}[{self.status}]"
