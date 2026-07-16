"""Per-tenant specialty threshold customization (plan Phase 10 — closes G6).

A ``SpecialtyThresholdPolicy`` is one practice's override of a specialty pack's default
threshold parameters (e.g. a practice that runs a tighter A1c target or a looser TSH upper
limit). It is the persistence behind the Phase 10 exit gate *"per-tenant threshold
customization works without code change"*: the overrides are DATA, applied deterministically
at rule-load time by ``core.bind_parameters`` — no rule YAML is edited, no code ships.

Overrides are tenant-scoped and RLS-isolated. A version counter increments on every change so
the resolver can key its cache and the audit trail can pin which policy produced a decision.
"""
from __future__ import annotations

from django.db import models

from core.models import TenantScopedModel


class SpecialtyThresholdPolicy(TenantScopedModel):
    # The pack's primary specialty key (matches SpecialtyPack.specialty / catalog key).
    specialty = models.CharField(max_length=64, db_index=True)
    # Overrides: {parameter_name: value}. Only declared pack parameters may appear (enforced
    # in the service); the effective value is pack default overlaid with this map.
    overrides = models.JSONField(default=dict)
    version = models.PositiveIntegerField(default=1)
    updated_by = models.CharField(max_length=128, blank=True, default="")

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["tenant_id", "specialty"], name="uq_specialty_threshold_policy",
            )
        ]
        indexes = [models.Index(fields=["tenant_id", "specialty"])]
        ordering = ["specialty"]

    def __str__(self) -> str:
        return f"threshold-policy:{self.specialty}:v{self.version}"
