"""Public service interface for the Context module (spec §7.4).

The ONLY entry point other modules may use to interact with this domain.
Keep clinical logic here, not in controllers.
"""
from __future__ import annotations

from clinara.middleware.tenant import current_tenant_id, set_db_tenant

from .core import build_context_panel
from .models import ContextSnapshotRecord


class SnapshotNotFound(LookupError):
    """No context snapshot exists for the requested workflow in this tenant."""


def chart_context_panel(*, tenant_id: str, workflow_id: str) -> dict:
    """Return the clinician-facing chart-context panel for a workflow (plan Phase 8 — G5).

    Reads the immutable ``ContextSnapshotRecord`` the engine already produced for the item and
    projects it into labs / patient-context / provenance (see ``core.build_context_panel``) —
    a presentation over existing data, so it surfaces exactly what the decision was based on
    with full freshness/provenance and adds nothing. Raises ``SnapshotNotFound`` if none.
    """
    current_tenant_id.set(str(tenant_id))
    set_db_tenant(str(tenant_id))
    record = (
        ContextSnapshotRecord.objects.filter(tenant_id=tenant_id, workflow_id=workflow_id)
        .order_by("-created_at")
        .first()
    )
    if record is None:
        raise SnapshotNotFound(f"no snapshot for workflow {workflow_id}")
    panel = build_context_panel(facts=record.facts, provenance=record.provenance)
    panel["workflow_id"] = str(record.workflow_id)
    panel["patient_external_id"] = record.patient_external_id
    panel["snapshot_hash"] = record.snapshot_hash
    return panel


__all__ = ["chart_context_panel", "build_context_panel", "SnapshotNotFound"]
