"""API v1 — Patient Message Intelligence surface (plan Phase 5; spec §6.2).

Thin HTTP layer over ``domains.messages.services``. Ingest a patient message → deterministic
red-flag scan + classification + urgency → routed/escalated reviewable item; clinicians
respond/route/escalate/resolve. Emergencies escalate regardless of model output; high-risk
categories are never auto-resolved. Tenant is resolved from the authenticated user.
"""
from __future__ import annotations

from django.urls import path
from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.request import Request
from rest_framework.response import Response

from domains.messages import core
from domains.messages import services as messages
from domains.messages.models import PatientMessage


def _tenant(request: Request) -> str | None:
    return getattr(request.user, "organization_id", None)


def _actor(request: Request) -> str:
    return getattr(request.user, "username", "unknown")


def _summary(m: PatientMessage) -> dict:
    return {
        "id": str(m.id), "patient_external_id": m.patient_external_id,
        "language": m.language, "category": m.category, "urgency": m.urgency,
        "red_flags": m.red_flags, "destination": m.destination,
        "auto_resolvable": m.auto_resolvable, "status": m.status,
        "created_at": m.created_at.isoformat(),
    }


def _detail(m: PatientMessage) -> dict:
    c = m.classifications.order_by("-created_at").first()
    data = _summary(m)
    data.update({
        # The verbatim inbound message (stored unmutated per spec §6.2). Surfaced only in the
        # detail view — "the original is always one tap away" — not in the list summaries.
        "original_text": m.original_text,
        "reason_codes": m.reason_codes,
        "draft_response": m.draft_response or None,
        "summary": c.summary if c else "",
        "symptoms": c.symptoms if c else [],
        "available_actions": ["respond", "route", "escalate", "resolve"],
        "reviews": [
            {"action": r.action, "actor": r.actor, "at": r.created_at.isoformat()}
            for r in m.reviews.all()
        ],
    })
    return data


@api_view(["POST"])
def ingest(request: Request) -> Response:
    tenant_id = _tenant(request)
    if not tenant_id:
        return Response({"detail": "no tenant context"}, status=status.HTTP_403_FORBIDDEN)
    try:
        message = messages.process_message(
            tenant_id=str(tenant_id), payload=request.data,
            context_patient_id=request.data.get("context_patient_id"),
        )
    except KeyError as exc:
        return Response({"detail": f"missing field {exc}"}, status=status.HTTP_400_BAD_REQUEST)
    except core.ContaminationError as exc:
        return Response({"detail": str(exc), "contamination_blocked": True},
                        status=status.HTTP_409_CONFLICT)
    return Response({"status": "processed", "message": _summary(message)},
                    status=status.HTTP_201_CREATED)


@api_view(["GET"])
def message_list(request: Request) -> Response:
    tenant_id = _tenant(request)
    qs = PatientMessage.objects.filter(tenant_id=tenant_id)
    if (s := request.query_params.get("status")):
        qs = qs.filter(status=s)
    if (u := request.query_params.get("urgency")):
        qs = qs.filter(urgency=u)
    return Response({"results": [_summary(m) for m in qs[:200]]})


@api_view(["GET"])
def message_detail(request: Request, message_id: str) -> Response:
    tenant_id = _tenant(request)
    m = PatientMessage.objects.filter(id=message_id, tenant_id=tenant_id).first()
    if m is None:
        return Response({"detail": "not found"}, status=status.HTTP_404_NOT_FOUND)
    return Response(_detail(m))


def _action_view(action: str):
    @api_view(["POST"])
    def view(request: Request, message_id: str) -> Response:
        tenant_id = _tenant(request)
        actor = _actor(request)
        try:
            if action == "respond":
                m = messages.respond(message_id, tenant_id=str(tenant_id), actor=actor,
                                     response_text=request.data.get("response_text", ""))
            elif action == "route":
                m = messages.route_to(message_id, tenant_id=str(tenant_id), actor=actor,
                                      reason=request.data.get("reason", ""))
            elif action == "escalate":
                m = messages.escalate(message_id, tenant_id=str(tenant_id), actor=actor,
                                      reason=request.data.get("reason", "clinician escalation"))
            else:  # resolve
                m = messages.resolve(message_id, tenant_id=str(tenant_id), actor=actor)
        except PatientMessage.DoesNotExist:
            return Response({"detail": "not found"}, status=status.HTTP_404_NOT_FOUND)
        return Response(_summary(m))

    return view


urlpatterns = [
    path("messages/ingest", ingest, name="messages-ingest"),
    path("messages", message_list, name="message-list"),
    path("messages/<uuid:message_id>", message_detail, name="message-detail"),
    path("messages/<uuid:message_id>/respond", _action_view("respond"), name="message-respond"),
    path("messages/<uuid:message_id>/route", _action_view("route"), name="message-route"),
    path("messages/<uuid:message_id>/escalate", _action_view("escalate"), name="message-escalate"),
    path("messages/<uuid:message_id>/resolve", _action_view("resolve"), name="message-resolve"),
]
