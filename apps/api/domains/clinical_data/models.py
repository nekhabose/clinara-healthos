"""Clinical Data persistence (plan Phase 1 data-model deltas).

Canonical, tenant-scoped storage for patient references and observations. Every row is
``TenantScopedModel`` so PostgreSQL RLS isolates it. Raw vendor payloads are kept on the
``integrations.InboundMessage`` this observation was parsed from (never dropped).
"""
from __future__ import annotations

from django.db import models

from core.models import TenantScopedModel


class PatientReference(TenantScopedModel):
    """Internal handle for a patient. Holds no raw PHI identifiers (MRN is hashed)."""

    external_id = models.CharField(max_length=128)  # EHR/source patient id
    mrn_hash = models.CharField(max_length=64, blank=True, default="")

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["tenant_id", "external_id"], name="uq_patient_ref_tenant_external"
            )
        ]

    def __str__(self) -> str:
        return f"patient:{self.external_id}"


class Observation(TenantScopedModel):
    """A canonicalized lab/diagnostic observation (spec §8.2)."""

    patient = models.ForeignKey(
        PatientReference, on_delete=models.CASCADE, related_name="observations"
    )
    code_system = models.CharField(max_length=32)
    code = models.CharField(max_length=64)
    marker = models.CharField(max_length=64, db_index=True)
    value = models.FloatField()                 # canonical-unit value
    unit = models.CharField(max_length=32)
    original_value = models.FloatField()
    original_unit = models.CharField(max_length=32, blank=True, default="")
    observed_at = models.DateTimeField()
    inbound_message_id = models.UUIDField(null=True, blank=True)  # raw payload pointer

    class Meta:
        indexes = [models.Index(fields=["tenant_id", "patient", "marker", "observed_at"])]
        ordering = ["-observed_at"]

    def __str__(self) -> str:
        return f"{self.marker}={self.value}{self.unit}@{self.observed_at:%Y-%m-%d}"
