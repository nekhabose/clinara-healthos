"""API v1 — Production EHR Integration surface (plan Phase 3; spec §6.7, §6.10.2).

Thin HTTP layer over the hardened gateway, monitoring, dead-letter replay, and delivery
services. Operators register interfaces, watch health/alerts, inspect + replay dead letters,
and drive EHR write-back; a SMART-on-FHIR launch endpoint returns the embedded-clinician
context (spec §6.10.2). Tenant is resolved from the authenticated user and RLS-scoped.
"""
from __future__ import annotations

from django.urls import path
from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.request import Request
from rest_framework.response import Response

from domains.delivery import services as delivery
from domains.integrations import gateway, monitoring
from domains.integrations import services as integrations
from domains.integrations.models import DeadLetterEvent, Integration, IntegrationError


def _tenant(request: Request) -> str | None:
    return getattr(request.user, "organization_id", None)


def _actor(request: Request) -> str:
    return getattr(request.user, "username", "unknown")


@api_view(["GET", "POST"])
def integrations_collection(request: Request) -> Response:
    tenant_id = _tenant(request)
    if not tenant_id:
        return Response({"detail": "no tenant context"}, status=status.HTTP_403_FORBIDDEN)
    if request.method == "GET":
        rows = Integration.objects.filter(tenant_id=tenant_id)
        return Response({"results": [
            {"id": str(i.id), "name": i.name, "kind": i.kind, "status": i.status}
            for i in rows
        ]})
    b = request.data
    integration = integrations.register_integration(
        tenant_id=str(tenant_id), name=b["name"], kind=b["kind"],
        source_system=b.get("source_system", ""),
        expected_interval_seconds=int(b.get("expected_interval_seconds", 0)),
        rate_capacity=int(b.get("rate_capacity", 100)),
        rate_refill_per_second=float(b.get("rate_refill_per_second", 50.0)),
    )
    return Response({"id": str(integration.id), "name": integration.name},
                    status=status.HTTP_201_CREATED)


@api_view(["GET"])
def integration_health(request: Request, integration_id: str) -> Response:
    tenant_id = _tenant(request)
    try:
        return Response(monitoring.integration_health(str(tenant_id), integration_id))
    except Integration.DoesNotExist:
        return Response({"detail": "not found"}, status=status.HTTP_404_NOT_FOUND)


@api_view(["GET"])
def integration_errors(request: Request, integration_id: str) -> Response:
    tenant_id = _tenant(request)
    rows = IntegrationError.objects.filter(
        tenant_id=tenant_id, integration_id=integration_id
    )[:200]
    return Response({"results": [
        {"kind": e.kind, "detail": e.detail, "at": e.created_at.isoformat()} for e in rows
    ]})


@api_view(["GET"])
def dashboard(request: Request) -> Response:
    tenant_id = _tenant(request)
    if not tenant_id:
        return Response({"detail": "no tenant context"}, status=status.HTTP_403_FORBIDDEN)
    return Response(monitoring.dashboard(str(tenant_id)))


@api_view(["POST"])
def scan_gaps(request: Request) -> Response:
    tenant_id = _tenant(request)
    alerts = monitoring.scan_silent_gaps(str(tenant_id))
    return Response({"raised": [{"kind": a.kind, "integration": str(a.integration_id),
                                 "message": a.message} for a in alerts]})


@api_view(["POST"])
def receive(request: Request, integration_id: str) -> Response:
    """Ingest a message through the gateway. FHIR resource or {"hl7": "..."} raw message."""
    tenant_id = _tenant(request)
    try:
        integration = Integration.objects.get(id=integration_id, tenant_id=tenant_id)
    except Integration.DoesNotExist:
        return Response({"detail": "not found"}, status=status.HTTP_404_NOT_FOUND)
    body = request.data
    if "hl7" in body:
        result = gateway.receive_hl7(integration_id=str(integration.id),
                                     raw_message=body["hl7"])
    else:
        result = gateway.receive_fhir(integration_id=str(integration.id), resource=body)
    code = status.HTTP_202_ACCEPTED if result.get("status") in {
        "dead_lettered", "rate_limited", "queued_or_duplicate", "acknowledged"
    } else status.HTTP_201_CREATED
    return Response(result, status=code)


@api_view(["POST"])
def replay_dead_letter(request: Request, dead_letter_id: str) -> Response:
    tenant_id = _tenant(request)
    try:
        result = gateway.replay_dead_letter(tenant_id=str(tenant_id),
                                            dead_letter_id=dead_letter_id)
    except DeadLetterEvent.DoesNotExist:
        return Response({"detail": "not found"}, status=status.HTTP_404_NOT_FOUND)
    return Response(result)


# ---- Delivery / write-back ----

@api_view(["POST"])
def write_back(request: Request, workflow_id: str) -> Response:
    tenant_id = _tenant(request)
    b = request.data
    message, created = delivery.queue_write_back(
        tenant_id=str(tenant_id), workflow_id=str(workflow_id),
        channel=b.get("channel", "ehr_task"), target=b.get("target", "care_team"),
        subject=b.get("subject", ""), body=b.get("body", ""), actor=_actor(request),
    )
    return Response({"id": str(message.id), "status": message.status, "created": created},
                    status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)


@api_view(["POST"])
def deliver(request: Request, message_id: str) -> Response:
    tenant_id = _tenant(request)
    try:
        message = delivery.deliver(tenant_id=str(tenant_id), message_id=message_id,
                                   actor=_actor(request))
    except Exception:  # noqa: BLE001
        return Response({"detail": "not found"}, status=status.HTTP_404_NOT_FOUND)
    return Response({"id": str(message.id), "status": message.status,
                     "external_id": message.external_id or None})


@api_view(["POST"])
def release(request: Request, workflow_id: str) -> Response:
    """Release an approved result: exactly one patient-portal message + one EHR task,
    idempotent per workflow (plan Phase 7). Delivers through the configured EHR adapter when
    one is provided, otherwise the confirming stub."""
    tenant_id = _tenant(request)
    if not tenant_id:
        return Response({"detail": "no tenant context"}, status=status.HTTP_403_FORBIDDEN)
    b = request.data
    result = delivery.release_result(
        tenant_id=str(tenant_id), workflow_id=str(workflow_id),
        patient_target=b.get("patient_target", ""),
        care_team_target=b.get("care_team_target", "care_team"),
        portal_subject=b.get("subject", ""), portal_body=b.get("body", ""),
        task_note=b.get("task_note", ""), actor=_actor(request),
    )
    return Response(result, status=status.HTTP_201_CREATED)


@api_view(["GET"])
def write_back_health(request: Request) -> Response:
    """Write-back health + degraded verdict for the ops dashboard (plan Phase 7)."""
    tenant_id = _tenant(request)
    if not tenant_id:
        return Response({"detail": "no tenant context"}, status=status.HTTP_403_FORBIDDEN)
    return Response(delivery.write_back_health(str(tenant_id)))


# ---- SMART on FHIR embedded launch (spec §6.10.2) ----

@api_view(["GET"])
def smart_launch(request: Request) -> Response:
    """Return the embedded-clinician launch context for an EHR SMART launch (spec §6.10.2)."""
    tenant_id = _tenant(request)
    if not tenant_id:
        return Response({"detail": "no tenant context"}, status=status.HTTP_403_FORBIDDEN)
    patient = request.query_params.get("patient", "")
    return Response({
        "embedded": True,
        "tenant_id": str(tenant_id),
        "patient": patient,
        "clinician": _actor(request),
        "surface": "clinician-review",
    })


urlpatterns = [
    path("integrations", integrations_collection, name="integrations-collection"),
    path("integrations/dashboard", dashboard, name="integrations-dashboard"),
    path("integrations/scan-gaps", scan_gaps, name="integrations-scan-gaps"),
    path("integrations/<uuid:integration_id>/health", integration_health,
         name="integration-health"),
    path("integrations/<uuid:integration_id>/errors", integration_errors,
         name="integration-errors"),
    path("integrations/<uuid:integration_id>/receive", receive, name="integration-receive"),
    path("dead-letters/<uuid:dead_letter_id>/replay", replay_dead_letter,
         name="dead-letter-replay"),
    path("workflows/<uuid:workflow_id>/write-back", write_back, name="workflow-write-back"),
    path("workflows/<uuid:workflow_id>/release", release, name="workflow-release"),
    path("outbound/<uuid:message_id>/deliver", deliver, name="outbound-deliver"),
    path("delivery/health", write_back_health, name="delivery-health"),
    path("smart/launch", smart_launch, name="smart-launch"),
]
