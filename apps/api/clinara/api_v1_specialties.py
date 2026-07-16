"""API v1 — Specialty Protocol Breadth surface (plan Phase 10; closes G6).

Thin HTTP layer over the specialties service: browse the ambulatory specialty registry and
its pack coverage, inspect the validated protocol packs and their effective (tenant-resolved)
thresholds, and customize a pack's thresholds for the practice. A threshold override is
validated against the full pack activation gate before it is stored, so a customization can
never weaken safety — an unsafe value returns 422, not a live unsafe rule. Tenant is resolved
from the authenticated user and RLS-scoped.
"""
from __future__ import annotations

from django.urls import path
from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.request import Request
from rest_framework.response import Response

from domains.specialties import core, services


def _tenant(request: Request) -> str | None:
    return getattr(request.user, "organization_id", None)


def _actor(request: Request) -> str:
    return getattr(request.user, "username", "unknown")


def _pack_summary(pack: core.SpecialtyPack, validation: core.PackValidation | None = None) -> dict:
    out = {
        "key": pack.specialty,
        "display_name": pack.display_name,
        "version": pack.version,
        "markers": pack.markers,
        "parameters": pack.parameters,
        "evidence": list(pack.evidence),
        "served_specialties": sorted(pack.served_specialties),
        "rule_count": len(pack.raw_rules),
        "test_count": len(pack.test_cases),
    }
    if validation is not None:
        out["validation"] = {
            "ok": validation.ok, "safety_ok": validation.safety_ok,
            "tests_passed": validation.test_passed, "tests_total": validation.test_total,
            "errors": validation.errors,
        }
    return out


@api_view(["GET"])
def list_specialties(request: Request) -> Response:
    """The ambulatory specialty registry annotated with pack coverage."""
    return Response({"results": services.list_specialties(),
                     "coverage": services.coverage_report()})


@api_view(["GET"])
def list_packs(request: Request) -> Response:
    validations = {v.specialty: v for v in services.validate_all()}
    results = [_pack_summary(p, validations.get(p.specialty)) for p in services.packs()]
    return Response({"results": results})


@api_view(["GET"])
def pack_detail(request: Request, key: str) -> Response:
    tenant_id = _tenant(request)
    try:
        pack = services.pack_for_specialty(key)
    except services.UnknownSpecialty:
        return Response({"detail": f"unknown pack {key!r}"}, status=status.HTTP_404_NOT_FOUND)
    summary = _pack_summary(pack, core.validate_pack(pack))
    if tenant_id:
        summary["effective_thresholds"] = services.effective_thresholds(tenant_id, key)
        summary["overrides"] = services.get_overrides(tenant_id, key)
    return Response(summary)


@api_view(["POST"])
def set_threshold(request: Request, key: str) -> Response:
    tenant_id = _tenant(request)
    if not tenant_id:
        return Response({"detail": "no tenant context"}, status=status.HTTP_403_FORBIDDEN)
    parameter = request.data.get("parameter")
    if parameter is None or "value" not in request.data:
        return Response({"detail": "parameter and value are required"},
                        status=status.HTTP_400_BAD_REQUEST)
    try:
        policy = services.set_threshold(
            tenant_id=tenant_id, specialty=key, parameter=parameter,
            value=request.data["value"], actor=_actor(request),
        )
    except services.UnknownSpecialty:
        return Response({"detail": f"unknown pack {key!r}"}, status=status.HTTP_404_NOT_FOUND)
    except services.ThresholdRejected as exc:
        return Response({"detail": str(exc)}, status=status.HTTP_422_UNPROCESSABLE_ENTITY)
    return Response({
        "key": key, "version": policy.version, "overrides": policy.overrides,
        "effective_thresholds": services.effective_thresholds(tenant_id, key),
    })


@api_view(["POST"])
def reset_thresholds(request: Request, key: str) -> Response:
    tenant_id = _tenant(request)
    if not tenant_id:
        return Response({"detail": "no tenant context"}, status=status.HTTP_403_FORBIDDEN)
    try:
        services.reset_thresholds(tenant_id=tenant_id, specialty=key, actor=_actor(request))
    except services.UnknownSpecialty:
        return Response({"detail": f"unknown pack {key!r}"}, status=status.HTTP_404_NOT_FOUND)
    return Response({"key": key, "overrides": services.get_overrides(tenant_id, key),
                     "effective_thresholds": services.effective_thresholds(tenant_id, key)})


urlpatterns = [
    path("specialties", list_specialties),
    path("specialties/packs", list_packs),
    path("specialties/packs/<str:key>", pack_detail),
    path("specialties/packs/<str:key>/thresholds", set_threshold),
    path("specialties/packs/<str:key>/thresholds/reset", reset_thresholds),
]
