"""Audit service interface (spec §10.4, plan cross-cutting foundations).

Every mutating service MUST call ``record(...)``. A CI lint flags DB writes with no
accompanying audit emit. Records are hash-chained per tenant for tamper evidence.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any

from django.db import transaction

from clinara.middleware.phi_safe_logging import correlation_id, scrub
from clinara.middleware.tenant import current_tenant_id

from .models import AuditEvent


def _content_hash(fields: dict[str, Any], prev_hash: str | None) -> str:
    material = json.dumps({"prev": prev_hash, **fields}, sort_keys=True, default=str)
    return hashlib.sha256(material.encode()).hexdigest()


@transaction.atomic
def record(
    *,
    actor: str,
    action: str,
    resource: str,
    reason: str = "",
    before_state: dict[str, Any] | None = None,
    after_state: dict[str, Any] | None = None,
    source_ip: str | None = None,
    session: str | None = None,
) -> AuditEvent:
    """Append one tamper-evident audit record for the current tenant.

    Before/after states are PHI-scrubbed defensively — the audit trail records *that*
    and *what kind of* change occurred, not raw patient identifiers.
    """
    tenant_id = current_tenant_id.get()

    last = (
        AuditEvent.objects.filter(tenant_id=tenant_id)
        .order_by("-timestamp")
        .values_list("record_hash", flat=True)
        .first()
    )

    fields = {
        "actor": actor,
        "action": action,
        "resource": resource,
        "tenant_id": tenant_id,
        "reason": reason,
        "before_state": scrub(before_state) if before_state else None,
        "after_state": scrub(after_state) if after_state else None,
        "correlation_id": correlation_id.get() or "",
    }
    return AuditEvent.objects.create(
        **fields,
        source_ip=source_ip,
        session=session,
        prev_hash=last,
        record_hash=_content_hash(fields, last),
    )
