"""Clinical Rule Studio persistence (plan Phase 2 data-model deltas).

A ``Protocol`` is the logical clinical policy; each ``ProtocolVersion`` is an immutable,
versioned rule body that moves through the governed lifecycle (spec §6.5.4). Versions carry
their own test cases, simulation runs, impact report, dual-approval record, and deployment
history. Clinical config is deployed through THIS pipeline — separately from application
code (spec §14.3) — which is the core Phase 2 differentiator.

Every model is ``TenantScopedModel`` so PostgreSQL RLS isolates authoring per tenant.
"""
from __future__ import annotations

from django.db import models

from core.models import TenantScopedModel


class Protocol(TenantScopedModel):
    """A named clinical policy for one canonical marker (owns many versions)."""

    key = models.SlugField(max_length=96)
    marker = models.CharField(max_length=64, db_index=True)
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True, default="")

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["tenant_id", "key"], name="uq_protocol_tenant_key")
        ]
        ordering = ["key"]

    def __str__(self) -> str:
        return f"protocol:{self.key}"


class ProtocolVersion(TenantScopedModel):
    """One immutable version of a protocol's rule body + its lifecycle state (spec §6.5.4)."""

    protocol = models.ForeignKey(Protocol, on_delete=models.CASCADE, related_name="versions")
    version = models.PositiveIntegerField()
    # The declarative rule (spec §6.5.3) as JSON — the exact shape ``Rule.model_validate``
    # consumes. Rules are DATA: authored here, never as application code (plan key decision).
    rule_body = models.JSONField()
    evidence_references = models.JSONField(default=list)
    state = models.CharField(max_length=16, default="draft", db_index=True)

    # Dual approval (spec §6.5.4): clinical + engineering sign-off recorded independently.
    clinical_approved_by = models.CharField(max_length=128, blank=True, default="")
    engineering_approved_by = models.CharField(max_length=128, blank=True, default="")

    # Analysis artifacts captured before activation.
    impact_report = models.JSONField(null=True, blank=True)
    test_results = models.JSONField(default=list)

    author = models.CharField(max_length=128, blank=True, default="")

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["tenant_id", "protocol", "version"], name="uq_version_protocol_number"
            )
        ]
        indexes = [models.Index(fields=["tenant_id", "state"])]
        ordering = ["protocol_id", "-version"]

    def __str__(self) -> str:
        return f"{self.protocol.key}@v{self.version}[{self.state}]"

    @property
    def dual_approved(self) -> bool:
        return bool(self.clinical_approved_by and self.engineering_approved_by)


class RuleTestCase(TenantScopedModel):
    """A required regression case for a version (activation gate — plan Phase 2 deliverable)."""

    version = models.ForeignKey(
        ProtocolVersion, on_delete=models.CASCADE, related_name="test_cases"
    )
    name = models.CharField(max_length=128)
    marker = models.CharField(max_length=64)
    specialty = models.CharField(max_length=64, blank=True, default="")
    facts = models.JSONField(default=dict)
    conflicting_facts = models.JSONField(default=list)
    expected_classification = models.CharField(max_length=48)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return f"testcase:{self.name}->{self.expected_classification}"


class SimulationRun(TenantScopedModel):
    """A de-identified simulation record (spec §6.5.6). Stores only synthetic scenarios."""

    version = models.ForeignKey(
        ProtocolVersion, on_delete=models.CASCADE, related_name="simulations"
    )
    scenario_count = models.PositiveIntegerField(default=0)
    changed_count = models.PositiveIntegerField(default=0)
    agreement_rate = models.FloatField(default=1.0)
    cases = models.JSONField(default=list)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"simulation:{self.version_id}:{self.agreement_rate:.2f}"


class DeploymentMode(models.TextChoices):
    SHADOW = "shadow", "Shadow"
    PROGRESSIVE = "progressive", "Progressive rollout"
    FULL = "full", "Full"


class DeploymentStatus(models.TextChoices):
    ACTIVE = "active", "Active"
    ROLLED_BACK = "rolled_back", "Rolled back"
    SUPERSEDED = "superseded", "Superseded"


class Deployment(TenantScopedModel):
    """A config release of one version to a target scope (spec §6.5.8).

    Clinical config deploys through this record — distinct from application CI/CD
    (spec §14.3). ``mode`` starts at shadow (evaluate, don't act), then progressive, then
    full. ``rollback_to_version`` names the safe version to revert to.
    """

    version = models.ForeignKey(
        ProtocolVersion, on_delete=models.CASCADE, related_name="deployments"
    )
    mode = models.CharField(max_length=16, choices=DeploymentMode.choices)
    rollout_percentage = models.PositiveIntegerField(default=100)
    target_scope = models.JSONField(default=dict)  # {specialties, sites, clinician_cohort}
    rollback_to_version = models.PositiveIntegerField(null=True, blank=True)
    monitoring_plan = models.JSONField(default=dict)
    status = models.CharField(
        max_length=16, choices=DeploymentStatus.choices,
        default=DeploymentStatus.ACTIVE, db_index=True,
    )
    conflicts_suppressed = models.BooleanField(default=False)
    deployed_by = models.CharField(max_length=128, blank=True, default="")

    class Meta:
        indexes = [models.Index(fields=["tenant_id", "status", "mode"])]
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"deploy:{self.version_id}:{self.mode}[{self.status}]"


class Rollback(TenantScopedModel):
    """An executed rollback (manual or automatic condition) — spec §6.5.8."""

    deployment = models.ForeignKey(
        Deployment, on_delete=models.CASCADE, related_name="rollbacks"
    )
    from_version = models.PositiveIntegerField()
    to_version = models.PositiveIntegerField(null=True, blank=True)
    automatic = models.BooleanField(default=False)
    reason = models.CharField(max_length=255)
    actor = models.CharField(max_length=128, blank=True, default="")

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"rollback:{self.from_version}->{self.to_version}"
