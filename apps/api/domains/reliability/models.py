"""SLO breach persistence (GA hardening — spec §12.4).

An SLO evaluation window that misses a target records a breach here so the ops SLO dashboard
and the release gate ("SLOs met / observability complete") have a durable, queryable history.
Platform-level metrics, not tenant PHI — not RLS-scoped.
"""
from __future__ import annotations

import uuid

from django.db import models


class SLOBreachRecord(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    slo_key = models.CharField(max_length=64, db_index=True)
    description = models.CharField(max_length=255)
    observed = models.FloatField()
    target = models.FloatField()
    window_label = models.CharField(max_length=64, blank=True, default="")
    detected_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [models.Index(fields=["slo_key", "detected_at"])]
        ordering = ["-detected_at"]

    def __str__(self) -> str:
        return f"{self.slo_key} observed={self.observed} target={self.target}"
