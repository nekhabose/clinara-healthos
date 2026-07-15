"""API v1 — Prescription & Refill Intelligence surface (plan Phase 4; spec §6.3).

Thin HTTP layer over ``domains.refills.services``. Ingest a refill request → deterministic
decision → reviewable workflow; nurses/prescribers approve/reject/route/escalate. Every
decision is traceable to the exact data used, and controlled substances always require a
human. Tenant is resolved from the authenticated user and RLS-scoped.
"""
from __future__ import annotations

from django.urls import path
from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.request import Request
from rest_framework.response import Response

from domains.refills import services as refills
from domains.refills.models import RefillWorkflow


def _tenant(request: Request) -> str | None:
    return getattr(request.user, "organization_id", None)


def _actor(request: Request) -> str:
    return getattr(request.user, "username", "unknown")


def _summary(w: RefillWorkflow) -> dict:
    return {
        "id": str(w.id), "workflow_type": w.workflow_type, "rxnorm": w.rxnorm,
        "medication_name": w.medication_name, "outcome": w.outcome, "status": w.status,
        "controlled_substance": w.controlled_substance,
        "automation_allowed": w.automation_allowed,
        "patient_external_id": w.patient_external_id, "created_at": w.created_at.isoformat(),
    }


def _detail(w: RefillWorkflow) -> dict:
    ev = w.evaluations.order_by("-created_at").first()
    data = _summary(w)
    data.update({
        "reason_codes": ev.reason_codes if ev else [],
        "required_actions": ev.required_actions if ev else [],
        "clinical_factors_used": ev.clinical_factors_used if ev else [],
        "available_actions": ["approve", "reject", "route", "escalate"],
        "reviews": [
            {"action": r.action, "actor": r.actor, "at": r.created_at.isoformat()}
            for r in w.reviews.all()
        ],
    })
    return data


@api_view(["POST"])
def ingest(request: Request) -> Response:
    tenant_id = _tenant(request)
    if not tenant_id:
        return Response({"detail": "no tenant context"}, status=status.HTTP_403_FORBIDDEN)
    try:
        workflow = refills.process_refill_request(tenant_id=str(tenant_id), payload=request.data)
    except KeyError as exc:
        return Response({"detail": f"missing field {exc}"}, status=status.HTTP_400_BAD_REQUEST)
    return Response({"status": "processed", "workflow": _summary(workflow)},
                    status=status.HTTP_201_CREATED)


@api_view(["GET"])
def workflow_list(request: Request) -> Response:
    tenant_id = _tenant(request)
    qs = RefillWorkflow.objects.filter(tenant_id=tenant_id)
    if (s := request.query_params.get("status")):
        qs = qs.filter(status=s)
    if (o := request.query_params.get("outcome")):
        qs = qs.filter(outcome=o)
    return Response({"results": [_summary(w) for w in qs[:200]]})


@api_view(["GET"])
def workflow_detail(request: Request, workflow_id: str) -> Response:
    tenant_id = _tenant(request)
    w = RefillWorkflow.objects.filter(id=workflow_id, tenant_id=tenant_id).first()
    if w is None:
        return Response({"detail": "not found"}, status=status.HTTP_404_NOT_FOUND)
    return Response(_detail(w))


def _action_view(action: str):
    @api_view(["POST"])
    def view(request: Request, workflow_id: str) -> Response:
        tenant_id = _tenant(request)
        actor = _actor(request)
        try:
            if action == "approve":
                w = refills.approve(workflow_id, tenant_id=str(tenant_id), actor=actor)
            elif action == "reject":
                w = refills.reject(workflow_id, tenant_id=str(tenant_id), actor=actor,
                                   reason=request.data.get("reason", ""))
            elif action == "route":
                w = refills.route(workflow_id, tenant_id=str(tenant_id), actor=actor,
                                  reason=request.data.get("reason", ""))
            else:  # escalate
                w = refills.escalate(workflow_id, tenant_id=str(tenant_id), actor=actor,
                                     reason=request.data.get("reason", "clinician escalation"))
        except RefillWorkflow.DoesNotExist:
            return Response({"detail": "not found"}, status=status.HTTP_404_NOT_FOUND)
        return Response(_summary(w))

    return view


urlpatterns = [
    path("refills/ingest", ingest, name="refills-ingest"),
    path("refills", workflow_list, name="refill-list"),
    path("refills/<uuid:workflow_id>", workflow_detail, name="refill-detail"),
    path("refills/<uuid:workflow_id>/approve", _action_view("approve"), name="refill-approve"),
    path("refills/<uuid:workflow_id>/reject", _action_view("reject"), name="refill-reject"),
    path("refills/<uuid:workflow_id>/route", _action_view("route"), name="refill-route"),
    path("refills/<uuid:workflow_id>/escalate", _action_view("escalate"), name="refill-escalate"),
]
