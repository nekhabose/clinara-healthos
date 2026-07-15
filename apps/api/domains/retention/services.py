"""Public service interface for Data Lifecycle & Compliance Hardening (plan Phase 11 — G7).

The ONLY entry point other modules use to interact with this domain. It owns per-tenant
retention policy, the scheduled minimization/purge run, and the BAA-termination hard-purge with
a certificate of destruction. The governance invariants that make destroying PHI safe to ship:

  * **Deterministic & bounded.** What gets purged is a pure function of (policy, clock, data):
    the pure ``core`` computes the cutoff and validates every window against the catalog bounds
    before a single row is touched. A window can never be zero or unbounded.
  * **Tenant-scoped, never cross-tenant.** Every purge binds the tenant (RLS session var) and
    filters ``tenant_id`` explicitly; a purge for tenant A can never reach tenant B's rows.
  * **The audit trail survives.** ``AuditEvent`` is append-only and is never a purge target;
    every purge instead *appends* one hash-chained ``data_purge`` record and the certificate
    counts how many audit events were retained — proving the trail was preserved.
  * **Provable scope.** Each run persists a ``PurgeRun`` (cutoffs + per-category counts) and, for
    a real purge, a content-hashed ``CertificateOfDestruction`` — an auditor can verify exactly
    what was destroyed and that the certificate was not altered.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass

from clinara_shared_types import EventType
from django.db import transaction
from django.utils import timezone

from clinara.middleware.phi_safe_logging import correlation_id as _correlation_id
from clinara.middleware.tenant import current_tenant_id, set_db_tenant
from core.outbox import publish_event
from domains.audit import services as audit
from domains.audit.models import AuditAction, AuditEvent

# PHI-bearing purge targets. This domain is the cross-cutting data-lifecycle owner, so it
# reaches directly into each domain's persistence to destroy expired rows — the one place that
# is allowed to, by design (the coding domain sets the same precedent reading context snapshots).
from domains.clinical_data.models import Observation, PatientReference
from domains.coding.models import CodingSuggestionRecord
from domains.context.models import ContextSnapshotRecord
from domains.delivery.models import OutboundMessage
from domains.feedback.models import ClinicianFeedback
from domains.integrations.models import DeadLetterEvent, InboundMessage
from domains.messages.models import PatientMessage
from domains.refills.models import AllergyIntolerance, MedicationStatement, RefillWorkflow
from domains.workflows.models import WorkflowInstance

from . import catalog, core
from .core import WindowRejected  # re-exported for callers/tests
from .models import CertificateOfDestruction, PurgeMode, PurgeRun, RetentionPolicy


def _bind(tenant_id: str) -> None:
    current_tenant_id.set(str(tenant_id))
    if not _correlation_id.get():
        _correlation_id.set(str(uuid.uuid4()))
    set_db_tenant(str(tenant_id))


# --------------------------------------------------------------------------------------
# Purge-target registry — category key → concrete ORM model(s)
# --------------------------------------------------------------------------------------

@dataclass(frozen=True)
class PurgeTarget:
    """One ORM model a category purges, and the timestamp the retention window is measured on.

    Children are swept by ``on_delete=CASCADE`` (message classifications/reviews, workflow
    evaluations/communications/reviews, delivery attempts, refill evaluations/reviews), so they
    need no explicit target. Ordered children-before-parents so a cascade never pre-empts a
    later target's own (already-computed) count.
    """

    category: str
    model: type
    timestamp_field: str = "created_at"


PURGE_TARGETS: tuple[PurgeTarget, ...] = (
    # Raw inbound PHI (90-day default window).
    PurgeTarget("raw_inbound", InboundMessage),
    PurgeTarget("dead_letters", DeadLetterEvent),
    PurgeTarget("patient_messages", PatientMessage),
    PurgeTarget("outbound_messages", OutboundMessage),
    # Derived clinical records.
    PurgeTarget("observations", Observation),
    PurgeTarget("context_snapshots", ContextSnapshotRecord),
    PurgeTarget("results_workflows", WorkflowInstance),
    PurgeTarget("refill_workflows", RefillWorkflow),
    PurgeTarget("coding_suggestions", CodingSuggestionRecord),
    PurgeTarget("clinician_feedback", ClinicianFeedback),
    # Reference/registry data (termination-only categories).
    PurgeTarget("medications", MedicationStatement),
    PurgeTarget("medications", AllergyIntolerance),
    PurgeTarget("patient_references", PatientReference),
)


def _targets_for(category: str) -> list[PurgeTarget]:
    return [t for t in PURGE_TARGETS if t.category == category]


# --------------------------------------------------------------------------------------
# Per-tenant retention policy
# --------------------------------------------------------------------------------------

def _overrides(tenant_id: str) -> dict[str, int]:
    policy = RetentionPolicy.objects.filter(tenant_id=tenant_id).first()
    return dict(policy.window_overrides) if policy else {}


def effective_windows(tenant_id: str) -> dict[str, int]:
    """The {category: days} the scheduler will use — defaults overlaid with tenant overrides."""
    _bind(tenant_id)
    return core.resolve_windows(_overrides(tenant_id))


def get_policy(tenant_id: str) -> RetentionPolicy | None:
    _bind(tenant_id)
    return RetentionPolicy.objects.filter(tenant_id=tenant_id).first()


def set_retention_window(
    *, tenant_id: str, category: str, days: int, actor: str = "system",
) -> RetentionPolicy:
    """Override one category's retention window for a practice (validated + audited).

    ``core.validate_window`` rejects an unknown category or a window outside the catalog bounds
    BEFORE anything is persisted, so a practice can never set a zero or unbounded window.
    """
    _bind(tenant_id)
    core.validate_window(category, days)  # raises WindowRejected
    with transaction.atomic():
        policy, created = RetentionPolicy.objects.select_for_update().get_or_create(
            tenant_id=tenant_id,
            defaults={"window_overrides": {category: days}, "updated_by": actor},
        )
        before = catalog.DEFAULT_WINDOWS[category] if created else \
            policy.window_overrides.get(category, catalog.DEFAULT_WINDOWS[category])
        if not created:
            policy.window_overrides = {**policy.window_overrides, category: days}
            policy.updated_by = actor
            policy.version = policy.version + 1
            policy.save(update_fields=["window_overrides", "updated_by", "version", "updated_at"])
        audit.record(
            actor=actor, action="retention_policy_updated",
            resource=f"retention_policy:{tenant_id}", reason=category,
            before_state={"category": category, "days": before},
            after_state={"category": category, "days": days, "version": policy.version},
        )
        publish_event(
            event_type=EventType.RETENTION_POLICY_UPDATED.value,
            idempotency_key=f"retention-policy:{tenant_id}:{category}:{policy.version}",
            payload={"category": category, "days": days, "version": policy.version,
                     "actor": actor},
        )
    return policy


def reset_retention_windows(*, tenant_id: str, actor: str = "system") -> RetentionPolicy | None:
    """Clear a practice's overrides back to the minimal-necessary defaults (audited)."""
    _bind(tenant_id)
    with transaction.atomic():
        policy = RetentionPolicy.objects.select_for_update().filter(tenant_id=tenant_id).first()
        if policy is None:
            return None
        before = dict(policy.window_overrides)
        policy.window_overrides = {}
        policy.updated_by = actor
        policy.version = policy.version + 1
        policy.save(update_fields=["window_overrides", "updated_by", "version", "updated_at"])
        audit.record(
            actor=actor, action="retention_policy_reset",
            resource=f"retention_policy:{tenant_id}", reason="reset_to_defaults",
            before_state={"overrides": before}, after_state={"version": policy.version},
        )
        publish_event(
            event_type=EventType.RETENTION_POLICY_UPDATED.value,
            idempotency_key=f"retention-policy-reset:{tenant_id}:{policy.version}",
            payload={"reset": True, "version": policy.version, "actor": actor},
        )
    return policy


# --------------------------------------------------------------------------------------
# Purge execution (the deterministic, audited, certified core)
# --------------------------------------------------------------------------------------

def _execute_purge(
    *, tenant_id: str, mode: str, categories: tuple[str, ...], now, dry_run: bool,
    actor: str, reason: str,
) -> tuple[PurgeRun, CertificateOfDestruction | None]:
    """Purge each category (windowed for scheduled, unbounded for termination); certify the run.

    All deletes + the audit record + the persisted run/certificate + the event are one atomic
    transaction: a crash leaves either the whole purge recorded or nothing at all.
    """
    _bind(tenant_id)
    now = now or timezone.now()
    windows = core.resolve_windows(_overrides(tenant_id))

    lines: list[core.PurgeLine] = []
    cutoffs: dict[str, str] = {}
    counts: dict[str, int] = {}

    with transaction.atomic():
        for category in categories:
            cat_cutoff = None
            if mode == PurgeMode.SCHEDULED:
                cat_cutoff = core.cutoff_for(now, windows[category])
                cutoffs[category] = cat_cutoff.isoformat()
            purged = 0
            for target in _targets_for(category):
                qs = target.model.objects.filter(tenant_id=tenant_id)
                if cat_cutoff is not None:
                    qs = qs.filter(**{f"{target.timestamp_field}__lt": cat_cutoff})
                n = qs.count()
                purged += n
                if not dry_run and n:
                    qs.delete()  # cascades to child rows
            counts[category] = purged
            lines.append(core.PurgeLine(
                category=category, purged=purged,
                cutoff_iso=(cat_cutoff.isoformat() if cat_cutoff else None),
            ))

        # The audit trail is never purged — count what survived (before this run's own record).
        audit_retained = AuditEvent.objects.filter(tenant_id=tenant_id).count()
        certificate = core.build_certificate(
            tenant_id=tenant_id, mode=mode, lines=tuple(lines),
            audit_events_retained=audit_retained, issued_at_iso=now.isoformat(), dry_run=dry_run,
        )

        run = PurgeRun.objects.create(
            tenant_id=tenant_id, mode=mode, dry_run=dry_run, reason=reason, executed_by=actor,
            cutoffs=cutoffs, purged_counts=counts, total_purged=certificate.total_purged,
            audit_events_retained=audit_retained, certificate_hash=certificate.content_hash,
            finished_at=now,
        )
        cert_record: CertificateOfDestruction | None = None
        if not dry_run:
            cert_record = CertificateOfDestruction.objects.create(
                tenant_id=tenant_id, purge_run=run, mode=mode, dry_run=dry_run,
                lines=[line.as_dict() for line in certificate.lines],
                total_purged=certificate.total_purged, audit_events_retained=audit_retained,
                content_hash=certificate.content_hash,
            )

        if mode == PurgeMode.TERMINATION and not dry_run:
            policy, _created = RetentionPolicy.objects.select_for_update().get_or_create(
                tenant_id=tenant_id, defaults={"updated_by": actor},
            )
            policy.terminated = True
            policy.terminated_at = now
            policy.updated_by = actor
            policy.save(update_fields=["terminated", "terminated_at", "updated_by", "updated_at"])

        audit.record(
            actor=actor, action=AuditAction.DATA_PURGE.value,
            resource=f"retention:{mode}:{tenant_id}", reason=reason or mode,
            before_state={"cutoffs": cutoffs},
            after_state={
                "mode": mode, "dry_run": dry_run, "purged": counts,
                "total_purged": certificate.total_purged,
                "audit_events_retained": audit_retained,
                "certificate_hash": certificate.content_hash,
            },
        )
        event_type = (
            EventType.TENANT_DATA_PURGED if mode == PurgeMode.TERMINATION
            else EventType.DATA_PURGED
        )
        publish_event(
            event_type=event_type.value,
            idempotency_key=f"purge:{run.id}",
            payload={"mode": mode, "dry_run": dry_run,
                     "total_purged": certificate.total_purged,
                     "certificate_hash": certificate.content_hash},
        )
    return run, cert_record


def run_scheduled_purge(
    *, tenant_id: str, now=None, dry_run: bool = False, actor: str = "system",
) -> PurgeRun:
    """Sweep every windowed category past its per-tenant retention window. Idempotent.

    Re-running immediately purges nothing new (expired rows are already gone); the guarantee is
    inherent, not a special case. Pass ``dry_run=True`` to get the counts without deleting —
    the verification/proof-of-scope path.
    """
    run, _cert = _execute_purge(
        tenant_id=tenant_id, mode=PurgeMode.SCHEDULED, categories=catalog.windowed_categories(),
        now=now, dry_run=dry_run, actor=actor, reason="scheduled_minimization",
    )
    return run


def plan_scheduled_purge(*, tenant_id: str, now=None) -> PurgeRun:
    """A dry run: what the scheduled purge *would* destroy, without destroying it."""
    return run_scheduled_purge(tenant_id=tenant_id, now=now, dry_run=True, actor="system")


def terminate_tenant(
    *, tenant_id: str, actor: str, reason: str = "BAA termination", now=None,
) -> CertificateOfDestruction:
    """BAA offboarding: hard-purge ALL of a tenant's PHI and issue a certificate of destruction.

    Purges every category (no window), marks the policy terminated, and returns the tamper-evident
    certificate. The audit trail is preserved and the certificate records how many audit events
    were retained.
    """
    _run, certificate = _execute_purge(
        tenant_id=tenant_id, mode=PurgeMode.TERMINATION, categories=catalog.all_categories(),
        now=now, dry_run=False, actor=actor, reason=reason,
    )
    assert certificate is not None  # termination is never a dry run
    return certificate


def purge_all_tenants(now=None) -> int:
    """Run the scheduled purge for every active, non-terminated tenant. Returns total purged.

    Invoked by the Celery beat task. Binds each tenant's RLS context before touching its rows.
    """
    from domains.tenants.models import Organization

    total = 0
    for org in Organization.objects.filter(is_active=True):
        _bind(str(org.id))
        if RetentionPolicy.objects.filter(tenant_id=org.id, terminated=True).exists():
            continue  # a terminated tenant retains no PHI — nothing to sweep
        run = run_scheduled_purge(tenant_id=str(org.id), now=now)
        total += run.total_purged
    return total


# --------------------------------------------------------------------------------------
# Read surface
# --------------------------------------------------------------------------------------

def list_purge_runs(*, tenant_id: str, mode: str | None = None) -> list[PurgeRun]:
    _bind(tenant_id)
    qs = PurgeRun.objects.filter(tenant_id=tenant_id)
    if mode:
        qs = qs.filter(mode=mode)
    return list(qs[:200])


def latest_certificate(*, tenant_id: str) -> CertificateOfDestruction | None:
    _bind(tenant_id)
    return CertificateOfDestruction.objects.filter(tenant_id=tenant_id).order_by(
        "-issued_at"
    ).first()


__all__ = [
    "PurgeTarget", "PURGE_TARGETS", "WindowRejected",
    "effective_windows", "get_policy", "set_retention_window", "reset_retention_windows",
    "run_scheduled_purge", "plan_scheduled_purge", "terminate_tenant", "purge_all_tenants",
    "list_purge_runs", "latest_certificate",
]
