"""Retention & purge persistence (plan Phase 11 — closes G7).

Three tenant-scoped, RLS-isolated records, none of which is ever itself a purge target (they
are the *proof* a purge happened and must survive it — they hold counts and hashes, no PHI):

  * ``RetentionPolicy`` — one practice's per-category window overrides (defaults live in the
    catalog). A ``version`` counter bumps on every change so a purge run can pin which policy
    produced it; a ``terminated`` flag records a completed BAA offboarding.
  * ``PurgeRun`` — one execution of the scheduled minimization job or a termination hard-purge:
    the cutoffs used, the per-category counts, whether it was a dry run, and the certificate
    digest. Append-only in practice (written once at completion).
  * ``CertificateOfDestruction`` — the auditable certificate emitted for a completed purge:
    the per-category lines, totals, retained-audit-event count, and a tamper-evident content
    hash (verifiable against ``core.build_certificate``). One per ``PurgeRun``.
"""
from __future__ import annotations

from django.db import models

from core.models import TenantScopedModel


class PurgeMode(models.TextChoices):
    SCHEDULED = "scheduled", "Scheduled minimization"
    TERMINATION = "termination", "BAA termination hard-purge"


class RetentionPolicy(TenantScopedModel):
    """Per-tenant retention windows. Effective window = catalog default overlaid with overrides."""

    # {category_key: days}. Only known catalog categories may appear (enforced in the service).
    window_overrides = models.JSONField(default=dict)
    version = models.PositiveIntegerField(default=1)
    updated_by = models.CharField(max_length=128, blank=True, default="")
    # Set once a BAA-termination hard-purge completes; the tenant retains no PHI thereafter.
    terminated = models.BooleanField(default=False, db_index=True)
    terminated_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["tenant_id"], name="uq_retention_policy_tenant"),
        ]
        indexes = [models.Index(fields=["tenant_id"])]
        ordering = ["-created_at"]

    def __str__(self) -> str:
        state = "terminated" if self.terminated else f"v{self.version}"
        return f"retention-policy:{self.tenant_id}:{state}"


class PurgeRun(TenantScopedModel):
    """The record of one purge execution (scheduled or termination)."""

    mode = models.CharField(max_length=16, choices=PurgeMode.choices, db_index=True)
    dry_run = models.BooleanField(default=False)
    reason = models.CharField(max_length=255, blank=True, default="")
    executed_by = models.CharField(max_length=128, default="system")
    # {category_key: iso8601 cutoff}. Empty for a termination purge (no window).
    cutoffs = models.JSONField(default=dict)
    # {category_key: count} — what was (or, for a dry run, would be) purged.
    purged_counts = models.JSONField(default=dict)
    total_purged = models.PositiveIntegerField(default=0)
    audit_events_retained = models.PositiveIntegerField(default=0)
    certificate_hash = models.CharField(max_length=64, blank=True, default="", db_index=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [models.Index(fields=["tenant_id", "mode"])]
        ordering = ["-created_at"]

    def __str__(self) -> str:
        kind = "dry-run" if self.dry_run else self.mode
        return f"purge-run:{kind}:{self.total_purged}"


class CertificateOfDestruction(TenantScopedModel):
    """A tamper-evident certificate of destruction for a completed purge (proof of scope)."""

    purge_run = models.OneToOneField(
        PurgeRun, on_delete=models.CASCADE, related_name="certificate"
    )
    mode = models.CharField(max_length=16, choices=PurgeMode.choices, db_index=True)
    dry_run = models.BooleanField(default=False)
    # [{category, purged, cutoff}] — the certificate lines exactly as hashed.
    lines = models.JSONField(default=list)
    total_purged = models.PositiveIntegerField(default=0)
    audit_events_retained = models.PositiveIntegerField(default=0)
    content_hash = models.CharField(max_length=64, db_index=True)
    issued_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [models.Index(fields=["tenant_id", "mode"])]
        ordering = ["-issued_at"]

    def __str__(self) -> str:
        return f"certificate:{self.mode}:{self.content_hash[:12]}"
