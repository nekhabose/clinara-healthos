"""API v1 — Analytics & Personalization surface (plan Phase 6; spec §12, §6.4.3).

Thin HTTP layer over the feedback + analytics services. Capture clinician feedback, view
governed dashboards, derive *pending* personalization recommendations, and approve/reject
them. Recommendations are inert until a human approves them; no endpoint applies a change
autonomously. Tenant is resolved from the authenticated user and RLS-scoped.
"""
from __future__ import annotations

from django.urls import path
from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.request import Request
from rest_framework.response import Response

from domains.analytics import services as analytics
from domains.analytics.models import ConfigurationRecommendation
from domains.feedback import services as feedback


def _tenant(request: Request) -> str | None:
    return getattr(request.user, "organization_id", None)


def _actor(request: Request) -> str:
    return getattr(request.user, "username", "unknown")


@api_view(["POST"])
def capture_feedback(request: Request) -> Response:
    tenant_id = _tenant(request)
    if not tenant_id:
        return Response({"detail": "no tenant context"}, status=status.HTTP_403_FORBIDDEN)
    b = request.data
    try:
        fb = feedback.capture(
            tenant_id=str(tenant_id), workflow_type=b["workflow_type"],
            workflow_id=b["workflow_id"], practitioner=b.get("practitioner", _actor(request)),
            action=b["action"], original_text=b.get("original_text", ""),
            edited_text=b.get("edited_text", ""), protocol_key=b.get("protocol_key", ""),
            specialty=b.get("specialty", ""), reason=b.get("reason", ""),
        )
    except KeyError as exc:
        return Response({"detail": f"missing field {exc}"}, status=status.HTTP_400_BAD_REQUEST)
    return Response({"id": str(fb.id), "action": fb.action}, status=status.HTTP_201_CREATED)


@api_view(["GET"])
def dashboards(request: Request) -> Response:
    tenant_id = _tenant(request)
    if not tenant_id:
        return Response({"detail": "no tenant context"}, status=status.HTTP_403_FORBIDDEN)
    return Response(analytics.dashboards(str(tenant_id)))


@api_view(["POST"])
def derive_preferences(request: Request) -> Response:
    tenant_id = _tenant(request)
    rec = analytics.derive_preferences(
        str(tenant_id), request.data["practitioner"],
        target=request.data.get("target", "results_template"),
        min_observations=int(request.data.get("min_observations", 3)),
    )
    if rec is None:
        return Response({"status": "insufficient_signal"}, status=status.HTTP_200_OK)
    return Response({"id": str(rec.id), "status": rec.status, "proposal": rec.proposal,
                     "rationale": rec.rationale}, status=status.HTTP_201_CREATED)


@api_view(["GET"])
def recommendations(request: Request) -> Response:
    tenant_id = _tenant(request)
    qs = ConfigurationRecommendation.objects.filter(tenant_id=tenant_id)
    if (s := request.query_params.get("status")):
        qs = qs.filter(status=s)
    return Response({"results": [
        {"id": str(r.id), "kind": r.kind, "target": r.target, "status": r.status,
         "proposal": r.proposal, "supporting_observations": r.supporting_observations}
        for r in qs[:200]
    ]})


@api_view(["POST"])
def approve_recommendation(request: Request, recommendation_id: str) -> Response:
    tenant_id = _tenant(request)
    try:
        rec = analytics.approve_recommendation(
            tenant_id=str(tenant_id), recommendation_id=recommendation_id, actor=_actor(request)
        )
    except ConfigurationRecommendation.DoesNotExist:
        return Response({"detail": "not found"}, status=status.HTTP_404_NOT_FOUND)
    except analytics.RecommendationError as exc:
        return Response({"detail": str(exc)}, status=status.HTTP_409_CONFLICT)
    return Response({"id": str(rec.id), "status": rec.status, "approved_by": rec.approved_by})


@api_view(["POST"])
def reject_recommendation(request: Request, recommendation_id: str) -> Response:
    tenant_id = _tenant(request)
    try:
        rec = analytics.reject_recommendation(
            tenant_id=str(tenant_id), recommendation_id=recommendation_id, actor=_actor(request)
        )
    except ConfigurationRecommendation.DoesNotExist:
        return Response({"detail": "not found"}, status=status.HTTP_404_NOT_FOUND)
    return Response({"id": str(rec.id), "status": rec.status})


urlpatterns = [
    path("feedback", capture_feedback, name="capture-feedback"),
    path("analytics/dashboards", dashboards, name="analytics-dashboards"),
    path("analytics/preferences/derive", derive_preferences, name="derive-preferences"),
    path("analytics/recommendations", recommendations, name="recommendations"),
    path("analytics/recommendations/<uuid:recommendation_id>/approve", approve_recommendation,
         name="approve-recommendation"),
    path("analytics/recommendations/<uuid:recommendation_id>/reject", reject_recommendation,
         name="reject-recommendation"),
]
