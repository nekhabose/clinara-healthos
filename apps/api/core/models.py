"""Platform base models: timestamps, tenant scoping (RLS), and the outbox.

Every tenant-owned table inherits ``TenantScopedModel``. The ``tenant_id`` column is
the anchor for PostgreSQL Row-Level Security; migrations add an RLS policy comparing
``tenant_id`` to the ``app.current_tenant`` session var set by TenantContextMiddleware.
"""
from __future__ import annotations

import uuid

from django.db import models


class TimeStampedModel(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class TenantScopedModel(TimeStampedModel):
    """Base for all tenant-owned data. Do NOT store cross-tenant rows in one instance."""

    tenant_id = models.UUIDField(db_index=True)

    class Meta:
        abstract = True


class OutboxStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    PUBLISHED = "published", "Published"
    FAILED = "failed", "Failed"
    DEAD_LETTER = "dead_letter", "Dead letter"


class DomainEventOutbox(TimeStampedModel):
    """Transactional outbox (plan §1.2 — guarantees no silent event loss).

    Domain events are written here inside the SAME DB transaction as the state change
    that produced them. A relay (core.tasks.relay_outbox) publishes PENDING rows to the
    event bus and marks them PUBLISHED. Envelope fields mirror spec §7.5.
    """

    tenant_id = models.UUIDField(db_index=True, null=True)
    event_type = models.CharField(max_length=100, db_index=True)
    schema_version = models.PositiveIntegerField(default=1)
    correlation_id = models.CharField(max_length=64, db_index=True)
    causation_id = models.CharField(max_length=64, null=True, blank=True)
    idempotency_key = models.CharField(max_length=200, unique=True)
    payload = models.JSONField()
    audit_metadata = models.JSONField(default=dict)

    status = models.CharField(
        max_length=16, choices=OutboxStatus.choices, default=OutboxStatus.PENDING, db_index=True
    )
    attempts = models.PositiveIntegerField(default=0)
    last_error = models.TextField(blank=True, default="")
    published_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [models.Index(fields=["status", "created_at"])]
        ordering = ["created_at"]

    def __str__(self) -> str:
        return f"{self.event_type}({self.idempotency_key})[{self.status}]"
