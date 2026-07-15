"""Attestation persistence (GA hardening — spec §10.1).

A generated attestation is stored with its evidence digest so an auditor can later verify the
exported report was not altered. Attestations summarize platform-wide control operation, not
tenant PHI — not RLS-scoped.
"""
from __future__ import annotations

import uuid

from django.db import models


class AttestationRecord(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    window_label = models.CharField(max_length=120)
    frameworks = models.JSONField(default=list)
    attested = models.BooleanField(db_index=True)
    evidence_digest = models.CharField(max_length=64, db_index=True)
    controls = models.JSONField(default=list)
    gaps = models.JSONField(default=list)
    generated_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-generated_at"]

    def __str__(self) -> str:
        state = "attested" if self.attested else "gaps"
        return f"{self.window_label}[{state}]"
