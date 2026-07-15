"""Pure retention/purge logic (plan Phase 11 — closes G7).

Django-free so every rule that governs *what gets destroyed* is deterministic and exhaustively
unit-testable in isolation (the same posture as ``coding/core.py`` and ``compliance/core.py``).
Persistence, ORM deletes, RLS binding, audit, and events live in ``services``; this module only:

  * resolves an effective per-category retention window (defaults overlaid with tenant overrides),
  * computes the deterministic purge cutoff for a window given a clock,
  * validates a proposed override against the catalog bounds, and
  * builds a tamper-evident **certificate of destruction** — a content-hashed record of exactly
    what was purged, keyed so the same purge always yields the same digest (an auditor can verify
    an exported certificate was not altered, exactly like the compliance attestation digest).

Two invariants are enforced here, before any row is touched:
  * **A window is always bounded** — ``validate_window`` rejects anything outside
    ``[MIN_RETENTION_DAYS, MAX_RETENTION_DAYS]`` or naming an unknown category.
  * **The audit trail is never a purge line** — it is not in the catalog, so it can never appear
    in a plan or certificate; the certificate instead *records* how many audit events were
    retained, proving the trail survived the purge.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timedelta

from . import catalog


class WindowRejected(ValueError):
    """A proposed retention window is unknown or outside the catalog's bounds."""


def resolve_windows(overrides: dict[str, int] | None) -> dict[str, int]:
    """Effective {category: days} — minimal-necessary defaults overlaid with tenant overrides.

    Only known categories from an override map are applied; an unknown key is ignored here (the
    service rejects it at write time, so it can never be persisted in the first place).
    """
    windows = dict(catalog.DEFAULT_WINDOWS)
    for key, days in (overrides or {}).items():
        if catalog.is_known_category(key):
            windows[key] = int(days)
    return windows


def validate_window(category: str, days: int) -> None:
    """Raise ``WindowRejected`` unless ``category`` is known and ``days`` is within bounds."""
    if not catalog.is_known_category(category):
        raise WindowRejected(f"unknown retention category {category!r}")
    if not isinstance(days, int) or isinstance(days, bool):
        raise WindowRejected(f"retention window for {category!r} must be an integer number of days")
    if days < catalog.MIN_RETENTION_DAYS or days > catalog.MAX_RETENTION_DAYS:
        raise WindowRejected(
            f"retention window {days} for {category!r} is outside "
            f"[{catalog.MIN_RETENTION_DAYS}, {catalog.MAX_RETENTION_DAYS}] days"
        )


def cutoff_for(now: datetime, days: int) -> datetime:
    """The instant before which a row is expired: rows with ``created_at < cutoff`` are purged."""
    return now - timedelta(days=days)


def is_expired(created_at: datetime, cutoff: datetime) -> bool:
    """Deterministic expiry test — strictly older than the cutoff (boundary rows are kept)."""
    return created_at < cutoff


@dataclass(frozen=True)
class PurgeLine:
    """One category's contribution to a purge: how many rows, against which cutoff."""

    category: str
    purged: int
    cutoff_iso: str | None  # None for a BAA-termination purge (no window — everything goes)

    def as_dict(self) -> dict:
        return {"category": self.category, "purged": self.purged, "cutoff": self.cutoff_iso}


@dataclass(frozen=True)
class DestructionCertificate:
    """A content-hashed, tamper-evident record of a completed purge (proof of scope).

    Contains **no PHI** — only per-category counts, the cutoffs, the retained-audit-event count,
    and a digest over all of it. ``mode`` is ``scheduled`` or ``termination``.
    """

    tenant_id: str
    mode: str
    lines: tuple[PurgeLine, ...]
    total_purged: int
    audit_events_retained: int
    issued_at_iso: str
    dry_run: bool
    content_hash: str

    def as_dict(self) -> dict:
        return {
            "tenant_id": self.tenant_id,
            "mode": self.mode,
            "lines": [line.as_dict() for line in self.lines],
            "total_purged": self.total_purged,
            "audit_events_retained": self.audit_events_retained,
            "issued_at": self.issued_at_iso,
            "dry_run": self.dry_run,
            "content_hash": self.content_hash,
        }


def _certificate_digest(
    *, tenant_id: str, mode: str, lines: tuple[PurgeLine, ...],
    total_purged: int, audit_events_retained: int, issued_at_iso: str, dry_run: bool,
) -> str:
    """SHA-256 over the canonical certificate content — deterministic for a given purge."""
    material = json.dumps(
        {
            "tenant_id": str(tenant_id),
            "mode": mode,
            "lines": [[line.category, line.purged, line.cutoff_iso] for line in lines],
            "total_purged": total_purged,
            "audit_events_retained": audit_events_retained,
            "issued_at": issued_at_iso,
            "dry_run": dry_run,
        },
        sort_keys=True,
    )
    return hashlib.sha256(material.encode()).hexdigest()


def build_certificate(
    *, tenant_id: str, mode: str, lines: tuple[PurgeLine, ...],
    audit_events_retained: int, issued_at_iso: str, dry_run: bool = False,
) -> DestructionCertificate:
    """Assemble a certificate of destruction from the per-category purge lines.

    ``total_purged`` is derived (never trusted from a caller) and the digest covers the whole
    content, so two runs that destroyed the same rows produce the same hash and any tampering is
    detectable.
    """
    ordered = tuple(sorted(lines, key=lambda line: line.category))
    total = sum(line.purged for line in ordered)
    digest = _certificate_digest(
        tenant_id=str(tenant_id), mode=mode, lines=ordered, total_purged=total,
        audit_events_retained=audit_events_retained, issued_at_iso=issued_at_iso, dry_run=dry_run,
    )
    return DestructionCertificate(
        tenant_id=str(tenant_id), mode=mode, lines=ordered, total_purged=total,
        audit_events_retained=audit_events_retained, issued_at_iso=issued_at_iso,
        dry_run=dry_run, content_hash=digest,
    )


__all__ = [
    "WindowRejected", "resolve_windows", "validate_window", "cutoff_for", "is_expired",
    "PurgeLine", "DestructionCertificate", "build_certificate",
]
