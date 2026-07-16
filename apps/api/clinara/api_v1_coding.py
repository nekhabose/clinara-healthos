"""API v1 — Billing & Coding Intelligence surface (plan Phase 9; closes G1).

Thin HTTP layer over the coding service. Analyse an encounter's chart context into
deterministic, evidence-linked coding suggestions; review them in a queue; and confirm /
reject / export them. Nothing is applied to a claim autonomously — a suggestion must be
human-confirmed before it can be exported. Tenant is resolved from the authenticated user
and RLS-scoped.
"""
from __future__ import annotations

from django.urls import path
from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.request import Request
from rest_framework.response import Response

from domains.coding import core, services


def _tenant(request: Request) -> str | None:
    return getattr(request.user, "organization_id", None)


def _actor(request: Request) -> str:
    return getattr(request.user, "username", "unknown")


def _problem_list(raw: list[dict] | None) -> list[core.ProblemListItem]:
    return [core.ProblemListItem(description=p.get("description", ""), code=p.get("code"),
                                 status=p.get("status", "active")) for p in (raw or [])]


def _encounter_dx(raw: list[dict] | None) -> list[core.EncounterDiagnosis]:
    return [core.EncounterDiagnosis(code=d["code"], description=d.get("description", ""))
            for d in (raw or [])]


def _serialize(rec) -> dict:
    return {
        "id": str(rec.id), "suggestion_type": rec.suggestion_type,
        "icd10_code": rec.icd10_code, "description": rec.description, "hcc": rec.hcc,
        "supersedes_code": rec.supersedes_code, "status": rec.status,
        "requires_provider_confirmation": rec.requires_provider_confirmation,
        "rationale": rec.rationale, "evidence": rec.evidence,
        "patient_external_id": rec.patient_external_id, "encounter_id": rec.encounter_id,
        "workflow_id": str(rec.workflow_id) if rec.workflow_id else None,
        "decided_by": rec.decided_by,
    }


@api_view(["POST"])
def analyze(request: Request) -> Response:
    tenant_id = _tenant(request)
    if not tenant_id:
        return Response({"detail": "no tenant context"}, status=status.HTTP_403_FORBIDDEN)
    b = request.data
    problem_list = _problem_list(b.get("problem_list"))
    encounter_dx = _encounter_dx(b.get("encounter_dx"))
    try:
        if b.get("workflow_id"):
            records = services.analyze_from_snapshot(
                tenant_id=str(tenant_id), workflow_id=b["workflow_id"],
                problem_list=problem_list, encounter_dx=encounter_dx,
                encounter_id=b.get("encounter_id", ""),
            )
        else:
            if not b.get("patient_external_id"):
                return Response({"detail": "patient_external_id or workflow_id required"},
                                status=status.HTTP_400_BAD_REQUEST)
            records = services.analyze_encounter(
                tenant_id=str(tenant_id), patient_external_id=b["patient_external_id"],
                problem_list=problem_list, encounter_dx=encounter_dx,
                facts=b.get("facts"), lab_values=b.get("lab_values"),
                encounter_id=b.get("encounter_id", ""),
            )
    except services.SuggestionNotFound as exc:
        return Response({"detail": str(exc)}, status=status.HTTP_404_NOT_FOUND)
    return Response({"results": [_serialize(r) for r in records]},
                    status=status.HTTP_201_CREATED)


@api_view(["GET"])
def suggestions(request: Request) -> Response:
    tenant_id = _tenant(request)
    if not tenant_id:
        return Response({"detail": "no tenant context"}, status=status.HTTP_403_FORBIDDEN)
    records = services.list_suggestions(
        tenant_id=str(tenant_id), status=request.query_params.get("status"),
        workflow_id=request.query_params.get("workflow_id"),
    )
    return Response({"results": [_serialize(r) for r in records]})


@api_view(["POST"])
def confirm(request: Request, suggestion_id: str) -> Response:
    return _decide(request, suggestion_id, services.confirm_suggestion)


@api_view(["POST"])
def reject(request: Request, suggestion_id: str) -> Response:
    return _decide(request, suggestion_id, services.reject_suggestion)


@api_view(["POST"])
def export(request: Request, suggestion_id: str) -> Response:
    return _decide(request, suggestion_id, services.export_suggestion, allow_reason=False)


def _decide(request: Request, suggestion_id: str, fn, *, allow_reason: bool = True) -> Response:
    tenant_id = _tenant(request)
    if not tenant_id:
        return Response({"detail": "no tenant context"}, status=status.HTTP_403_FORBIDDEN)
    kwargs = {"tenant_id": str(tenant_id), "suggestion_id": suggestion_id,
              "actor": _actor(request)}
    if allow_reason:
        kwargs["reason"] = request.data.get("reason", "")
    try:
        rec = fn(**kwargs)
    except services.SuggestionNotFound:
        return Response({"detail": "not found"}, status=status.HTTP_404_NOT_FOUND)
    except services.SuggestionStateError as exc:
        return Response({"detail": str(exc)}, status=status.HTTP_409_CONFLICT)
    return Response(_serialize(rec))


urlpatterns = [
    path("coding/analyze", analyze, name="coding-analyze"),
    path("coding/suggestions", suggestions, name="coding-suggestions"),
    path("coding/suggestions/<uuid:suggestion_id>/confirm", confirm, name="coding-confirm"),
    path("coding/suggestions/<uuid:suggestion_id>/reject", reject, name="coding-reject"),
    path("coding/suggestions/<uuid:suggestion_id>/export", export, name="coding-export"),
]
