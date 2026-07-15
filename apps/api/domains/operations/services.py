"""Operations service interface (spec §7.4).

The single entry point for parking work that cannot be processed. Nothing is dropped —
everything lands in a visible, queryable queue (plan §1.1 invariant 2).
"""
from __future__ import annotations

from typing import Any

from .models import OperationsQueueItem, QueueKind


def enqueue(
    *, tenant_id: str, kind: str, reference: str = "", detail: str = "",
    payload: dict[str, Any] | None = None,
) -> OperationsQueueItem:
    return OperationsQueueItem.objects.create(
        tenant_id=tenant_id, kind=kind, reference=reference, detail=detail,
        payload=payload or {},
    )


def open_items(tenant_id: str, kind: str | None = None):
    qs = OperationsQueueItem.objects.filter(tenant_id=tenant_id, status="open")
    return qs.filter(kind=kind) if kind else qs


__all__ = ["enqueue", "open_items", "QueueKind"]
