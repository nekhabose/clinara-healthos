"""Terminology persistence (plan Phase 1 — mapping + unknown-code queue).

``IntegrationMapping`` lets a tenant extend the seed LOINC map. ``MappingProposal`` is the
visible unknown-code queue: when a code has no mapping, the event is parked here (never
dropped) for a data steward to resolve (plan §1.1 invariant 2).
"""
from __future__ import annotations

from django.db import models

from core.models import TenantScopedModel


class IntegrationMapping(TenantScopedModel):
    code_system = models.CharField(max_length=32)
    code = models.CharField(max_length=64)
    marker = models.CharField(max_length=64)
    active = models.BooleanField(default=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["tenant_id", "code_system", "code"], name="uq_mapping_tenant_system_code"
            )
        ]

    def __str__(self) -> str:
        return f"{self.code_system}:{self.code}->{self.marker}"


class ProposalStatus(models.TextChoices):
    OPEN = "open", "Open"
    RESOLVED = "resolved", "Resolved"


class MappingProposal(TenantScopedModel):
    """Unknown-code queue entry (spec §6.1.6 — unknown code → queue, never guess)."""

    code_system = models.CharField(max_length=32)
    code = models.CharField(max_length=64)
    seen_count = models.PositiveIntegerField(default=1)
    sample_payload = models.JSONField(default=dict)
    status = models.CharField(
        max_length=16, choices=ProposalStatus.choices, default=ProposalStatus.OPEN, db_index=True
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["tenant_id", "code_system", "code"], name="uq_proposal_tenant_system_code"
            )
        ]

    def __str__(self) -> str:
        return f"unmapped {self.code_system}:{self.code} x{self.seen_count}"
