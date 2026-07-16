"""API v1 — Results Intelligence surface (plan Phase 1; spec §6.10.1 clinician view).

Thin HTTP layer over the domain services. Tenant is resolved from the authenticated user
(``organization_id``) and every request is already tenant-scoped by TenantContextMiddleware
(RLS). Clinician actions (approve/edit/override/escalate/reject) and replay map 1:1 to the
workflow service; each is audited and emits a domain event in the service layer.
"""
from __future__ import annotations

from django.urls import path
from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.request import Request
from rest_framework.response import Response

from domains.clinical_data.models import Observation
from domains.integrations import services as integrations
from domains.integrations.fhir import FhirParseError, parse_observation
from domains.workflows import services as workflows
from domains.workflows.models import (
    WorkflowInstance,
)


def _tenant(request: Request) -> str | None:
    return getattr(request.user, "organization_id", None)


def _summary(w: WorkflowInstance) -> dict:
    return {
        "id": str(w.id), "workflow_type": w.workflow_type, "marker": w.marker,
        "classification": w.classification, "priority": w.priority,
        "automation_status": w.automation_status, "status": w.status,
        "patient_external_id": w.patient_external_id, "created_at": w.created_at.isoformat(),
    }


def _detail(w: WorkflowInstance) -> dict:
    """The clinician review payload (spec §6.10.1)."""
    evaluation = w.evaluations.order_by("-created_at").first()
    comm = w.communications.order_by("-created_at").first()
    obs = Observation.objects.filter(id=w.observation_id).first() if w.observation_id else None
    decision = evaluation.decision if evaluation else {}
    data = _summary(w)
    data.update(
        {
            "recommended_action": decision.get("recommended_action"),
            "recommended_interval_days": decision.get("recommended_interval_days"),
            "reason_codes": decision.get("reason_codes", []),
            "clinical_facts_used": decision.get("clinical_facts_used", []),
            "matched_rule": {
                "id": evaluation.matched_rule_id or None,
                "version": evaluation.matched_rule_version,
                "critical": evaluation.critical_triggered,
            } if evaluation else None,
            "observation": {
                "value": obs.value, "unit": obs.unit, "observed_at": obs.observed_at.isoformat(),
            } if obs else None,
            "communication": {
                "template_key": comm.template_key or None,
                "patient_message_preview": comm.patient_message or None,
                "clinician_summary": comm.clinician_summary,
                "validation_passed": comm.validation_passed,
                "validation_failures": comm.validation_failures,
                "used_fallback": comm.used_fallback,
            } if comm else None,
            "available_actions": ["approve", "edit", "override", "escalate", "reject", "replay"],
            "reviews": [
                {"action": r.action, "actor": r.actor, "at": r.created_at.isoformat()}
                for r in w.reviews.all()
            ],
        }
    )
    return data


@api_view(["POST"])
def ingest(request: Request) -> Response:
    """Ingest a result (FHIR Observation or the simplified sandbox payload)."""
    tenant_id = _tenant(request)
    if not tenant_id:
        return Response({"detail": "no tenant context"}, status=status.HTTP_403_FORBIDDEN)

    body = request.data
    try:
        payload = parse_observation(body) if body.get("resourceType") == "Observation" else body
    except FhirParseError as exc:
        return Response({"detail": f"invalid FHIR: {exc}"}, status=status.HTTP_400_BAD_REQUEST)

    message, workflow, created = integrations.ingest_and_process(
        tenant_id=str(tenant_id), payload=payload
    )
    if workflow is None:
        # Parked (duplicate or unmapped code) — nothing dropped, visible on the ops queue.
        return Response(
            {"status": "queued_or_duplicate", "message_id": str(message.id),
             "created": created, "message_status": message.status},
            status=status.HTTP_202_ACCEPTED,
        )
    return Response(
        {"status": "processed", "workflow": _summary(workflow)},
        status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
    )


@api_view(["GET"])
def workflow_list(request: Request) -> Response:
    tenant_id = _tenant(request)
    qs = WorkflowInstance.objects.filter(tenant_id=tenant_id)
    if (s := request.query_params.get("status")):
        qs = qs.filter(status=s)
    if (p := request.query_params.get("priority")):
        qs = qs.filter(priority=p)
    return Response({"results": [_summary(w) for w in qs[:200]]})


@api_view(["GET"])
def workflow_detail(request: Request, workflow_id: str) -> Response:
    tenant_id = _tenant(request)
    w = WorkflowInstance.objects.filter(id=workflow_id, tenant_id=tenant_id).first()
    if w is None:
        return Response({"detail": "not found"}, status=status.HTTP_404_NOT_FOUND)
    return Response(_detail(w))


def _action_view(action: str):
    @api_view(["POST"])
    def view(request: Request, workflow_id: str) -> Response:
        tenant_id = _tenant(request)
        actor = getattr(request.user, "username", "unknown")
        try:
            if action == "approve":
                w = workflows.approve(workflow_id, tenant_id=str(tenant_id), actor=actor)
            elif action == "edit":
                w = workflows.edit(workflow_id, tenant_id=str(tenant_id), actor=actor,
                                   edited_message=request.data.get("edited_message", ""))
            elif action == "override":
                w = workflows.override(workflow_id, tenant_id=str(tenant_id), actor=actor,
                                       reason=request.data.get("reason", ""))
            elif action == "reject":
                w = workflows.reject(workflow_id, tenant_id=str(tenant_id), actor=actor,
                                     reason=request.data.get("reason", ""))
            elif action == "escalate":
                w = workflows.escalate(workflow_id, tenant_id=str(tenant_id), actor=actor,
                                       reason=request.data.get("reason", "clinician escalation"))
            else:  # replay
                return Response(workflows.replay(workflow_id, tenant_id=str(tenant_id)))
        except WorkflowInstance.DoesNotExist:
            return Response({"detail": "not found"}, status=status.HTTP_404_NOT_FOUND)
        return Response(_summary(w))

    return view


urlpatterns = [
    path("results/ingest", ingest, name="results-ingest"),
    path("workflows", workflow_list, name="workflow-list"),
    path("workflows/<uuid:workflow_id>", workflow_detail, name="workflow-detail"),
    path("workflows/<uuid:workflow_id>/approve", _action_view("approve"), name="workflow-approve"),
    path("workflows/<uuid:workflow_id>/edit", _action_view("edit"), name="workflow-edit"),
    path("workflows/<uuid:workflow_id>/override", _action_view("override"),
         name="workflow-override"),
    path("workflows/<uuid:workflow_id>/escalate", _action_view("escalate"),
         name="workflow-escalate"),
    path("workflows/<uuid:workflow_id>/reject", _action_view("reject"), name="workflow-reject"),
    path("workflows/<uuid:workflow_id>/replay", _action_view("replay"), name="workflow-replay"),
]
