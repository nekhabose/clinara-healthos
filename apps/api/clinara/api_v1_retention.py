"""API v1 — Data Lifecycle & Compliance Hardening surface (plan Phase 11; closes G7).

Thin HTTP layer over the retention service. Inspect and tune per-tenant retention windows, run
(or dry-run) the scheduled minimization purge, review purge history, and — gated to admins —
execute a BAA-termination hard-purge that returns a certificate of destruction. Tenant is
resolved from the authenticated user and RLS-scoped; nothing crosses a tenant boundary.
"""
from __future__ import annotations

from clinara_shared_types import Role
from django.urls import path
from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.request import Request
from rest_framework.response import Response

from domains.retention import catalog, services

# Roles allowed to trigger a destructive BAA-termination hard-purge.
_TERMINATION_ROLES = {Role.TENANT_ADMIN.value, Role.PLATFORM_ADMIN.value}


def _tenant(request: Request) -> str | None:
    return getattr(request.user, "organization_id", None)


def _actor(request: Request) -> str:
    return getattr(request.user, "username", "unknown")


def _serialize_run(run) -> dict:
    return {
        "id": str(run.id), "mode": run.mode, "dry_run": run.dry_run, "reason": run.reason,
        "executed_by": run.executed_by, "cutoffs": run.cutoffs, "purged_counts": run.purged_counts,
        "total_purged": run.total_purged, "audit_events_retained": run.audit_events_retained,
        "certificate_hash": run.certificate_hash,
        "finished_at": run.finished_at.isoformat() if run.finished_at else None,
    }


def _serialize_certificate(cert) -> dict:
    return {
        "id": str(cert.id), "purge_run_id": str(cert.purge_run_id), "mode": cert.mode,
        "dry_run": cert.dry_run, "lines": cert.lines, "total_purged": cert.total_purged,
        "audit_events_retained": cert.audit_events_retained, "content_hash": cert.content_hash,
        "issued_at": cert.issued_at.isoformat() if cert.issued_at else None,
    }


@api_view(["GET"])
def policy(request: Request) -> Response:
    tenant_id = _tenant(request)
    if not tenant_id:
        return Response({"detail": "no tenant context"}, status=status.HTTP_403_FORBIDDEN)
    windows = services.effective_windows(str(tenant_id))
    rec = services.get_policy(str(tenant_id))
    return Response({
        "windows": windows,
        "defaults": catalog.DEFAULT_WINDOWS,
        "categories": [
            {"key": c.key, "label": c.label, "windowed": c.windowed,
             "description": c.description, "default_days": c.default_days}
            for c in catalog.RETENTION_CATEGORIES
        ],
        "overrides": dict(rec.window_overrides) if rec else {},
        "version": rec.version if rec else 0,
        "terminated": rec.terminated if rec else False,
    })


@api_view(["PUT"])
def set_window(request: Request) -> Response:
    tenant_id = _tenant(request)
    if not tenant_id:
        return Response({"detail": "no tenant context"}, status=status.HTTP_403_FORBIDDEN)
    b = request.data
    category, days = b.get("category"), b.get("days")
    if category is None or days is None:
        return Response({"detail": "category and days are required"},
                        status=status.HTTP_400_BAD_REQUEST)
    try:
        rec = services.set_retention_window(
            tenant_id=str(tenant_id), category=str(category), days=int(days), actor=_actor(request),
        )
    except (ValueError, TypeError) as exc:
        # Includes core.WindowRejected (unknown category / out-of-bounds window).
        return Response({"detail": str(exc)}, status=status.HTTP_422_UNPROCESSABLE_ENTITY)
    return Response({"overrides": dict(rec.window_overrides), "version": rec.version})


@api_view(["POST"])
def purge(request: Request) -> Response:
    tenant_id = _tenant(request)
    if not tenant_id:
        return Response({"detail": "no tenant context"}, status=status.HTTP_403_FORBIDDEN)
    dry_run = bool(request.data.get("dry_run", False))
    run = services.run_scheduled_purge(
        tenant_id=str(tenant_id), dry_run=dry_run, actor=_actor(request),
    )
    return Response(_serialize_run(run), status=status.HTTP_201_CREATED)


@api_view(["GET"])
def runs(request: Request) -> Response:
    tenant_id = _tenant(request)
    if not tenant_id:
        return Response({"detail": "no tenant context"}, status=status.HTTP_403_FORBIDDEN)
    records = services.list_purge_runs(
        tenant_id=str(tenant_id), mode=request.query_params.get("mode"),
    )
    return Response({"results": [_serialize_run(r) for r in records]})


@api_view(["POST"])
def terminate(request: Request) -> Response:
    tenant_id = _tenant(request)
    if not tenant_id:
        return Response({"detail": "no tenant context"}, status=status.HTTP_403_FORBIDDEN)
    if getattr(request.user, "role", None) not in _TERMINATION_ROLES:
        return Response({"detail": "termination requires an admin or compliance-officer role"},
                        status=status.HTTP_403_FORBIDDEN)
    reason = request.data.get("reason", "BAA termination")
    cert = services.terminate_tenant(
        tenant_id=str(tenant_id), actor=_actor(request), reason=str(reason),
    )
    return Response(_serialize_certificate(cert), status=status.HTTP_201_CREATED)


@api_view(["GET"])
def certificate(request: Request) -> Response:
    tenant_id = _tenant(request)
    if not tenant_id:
        return Response({"detail": "no tenant context"}, status=status.HTTP_403_FORBIDDEN)
    cert = services.latest_certificate(tenant_id=str(tenant_id))
    if cert is None:
        return Response({"detail": "no certificate of destruction on record"},
                        status=status.HTTP_404_NOT_FOUND)
    return Response(_serialize_certificate(cert))


urlpatterns = [
    path("retention/policy", policy, name="retention-policy"),
    path("retention/policy/window", set_window, name="retention-set-window"),
    path("retention/purge", purge, name="retention-purge"),
    path("retention/runs", runs, name="retention-runs"),
    path("retention/terminate", terminate, name="retention-terminate"),
    path("retention/certificate", certificate, name="retention-certificate"),
]
