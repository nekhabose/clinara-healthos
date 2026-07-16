"""Terminology service interface (spec §7.4).

Resolves vendor codes to canonical markers, honouring tenant-specific ``IntegrationMapping``
overrides on top of the seed LOINC map. Unknown codes are recorded on the unknown-code
queue (a ``MappingProposal``) so they are visible and resolvable — never guessed.
"""
from __future__ import annotations

from typing import Any

from clinara_terminology import CanonicalMarker, UnknownCodeError, map_code

from .models import IntegrationMapping, MappingProposal


def resolve_marker(tenant_id: str, code_system: str, code: str) -> CanonicalMarker | None:
    """Return the canonical marker for a code, or ``None`` if unmapped (caller queues it)."""
    override = (
        IntegrationMapping.objects.filter(
            tenant_id=tenant_id, code_system=code_system, code=code, active=True
        )
        .values_list("marker", flat=True)
        .first()
    )
    if override:
        return CanonicalMarker(override)
    try:
        return map_code(code_system, code)
    except UnknownCodeError:
        return None


def record_unknown_code(
    *, tenant_id: str, code_system: str, code: str, sample_payload: dict[str, Any] | None = None
) -> MappingProposal:
    """Add or increment an unknown-code queue entry (spec §6.1.6)."""
    proposal, created = MappingProposal.objects.get_or_create(
        tenant_id=tenant_id, code_system=code_system, code=code,
        defaults={"sample_payload": sample_payload or {}},
    )
    if not created:
        proposal.seen_count += 1
        proposal.save(update_fields=["seen_count", "updated_at"])
    return proposal


__all__ = ["resolve_marker", "record_unknown_code"]
