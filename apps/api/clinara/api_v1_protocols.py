"""API v1 — Clinical Rule Studio surface (plan Phase 2; spec §6.5).

Thin HTTP layer over ``domains.protocols.services``. This is the authoring surface a
clinical programmer drives to create, simulate, impact-analyze, approve, deploy (shadow →
progressive → full), and roll back clinical logic **with no application code change** — the
Phase 2 differentiator. Tenant is resolved from the authenticated user and every request is
RLS-scoped; each mutating action is audited and emits a domain event in the service layer.
"""
from __future__ import annotations

from django.urls import path
from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.request import Request
from rest_framework.response import Response

from domains.protocols import core
from domains.protocols import services as protocols
from domains.protocols.models import Deployment, Protocol, ProtocolVersion


def _tenant(request: Request) -> str | None:
    return getattr(request.user, "organization_id", None)


def _actor(request: Request) -> str:
    return getattr(request.user, "username", "unknown")


def _version_summary(v: ProtocolVersion) -> dict:
    return {
        "id": str(v.id), "protocol_id": str(v.protocol_id), "version": v.version,
        "state": v.state, "dual_approved": v.dual_approved,
        "clinical_approved_by": v.clinical_approved_by or None,
        "engineering_approved_by": v.engineering_approved_by or None,
        "impact_report": v.impact_report, "test_results": v.test_results,
    }


@api_view(["GET", "POST"])
def protocols_collection(request: Request) -> Response:
    tenant_id = _tenant(request)
    if not tenant_id:
        return Response({"detail": "no tenant context"}, status=status.HTTP_403_FORBIDDEN)
    if request.method == "GET":
        rows = Protocol.objects.filter(tenant_id=tenant_id)
        return Response({"results": [
            {"id": str(p.id), "key": p.key, "marker": p.marker, "title": p.title}
            for p in rows
        ]})
    body = request.data
    p = protocols.create_protocol(
        tenant_id=str(tenant_id), key=body["key"], marker=body["marker"],
        title=body.get("title", body["key"]), description=body.get("description", ""),
        actor=_actor(request),
    )
    return Response({"id": str(p.id), "key": p.key, "marker": p.marker},
                    status=status.HTTP_201_CREATED)


@api_view(["POST"])
def create_version(request: Request, protocol_id: str) -> Response:
    tenant_id = _tenant(request)
    try:
        v = protocols.create_version(
            tenant_id=str(tenant_id), protocol_id=protocol_id,
            rule_body=request.data["rule_body"], author=_actor(request),
            evidence_references=request.data.get("evidence_references"),
        )
    except (ValueError, Protocol.DoesNotExist) as exc:
        return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
    return Response(_version_summary(v), status=status.HTTP_201_CREATED)


@api_view(["POST"])
def add_test_case(request: Request, version_id: str) -> Response:
    tenant_id = _tenant(request)
    body = request.data
    tc = protocols.add_test_case(
        tenant_id=str(tenant_id), version_id=version_id, name=body["name"],
        marker=body["marker"], facts=body.get("facts", {}),
        expected_classification=body["expected_classification"],
        specialty=body.get("specialty", ""),
        conflicting_facts=body.get("conflicting_facts"),
    )
    return Response({"id": str(tc.id), "name": tc.name}, status=status.HTTP_201_CREATED)


@api_view(["POST"])
def simulate(request: Request, version_id: str) -> Response:
    tenant_id = _tenant(request)
    run = protocols.simulate(
        tenant_id=str(tenant_id), version_id=version_id,
        scenarios=request.data.get("scenarios"), actor=_actor(request),
    )
    return Response({
        "id": str(run.id), "scenario_count": run.scenario_count,
        "changed_count": run.changed_count, "agreement_rate": run.agreement_rate,
        "cases": run.cases,
    })


@api_view(["POST"])
def impact(request: Request, version_id: str) -> Response:
    tenant_id = _tenant(request)
    report = protocols.analyze_impact(
        tenant_id=str(tenant_id), version_id=version_id,
        scenarios=request.data.get("scenarios"),
    )
    return Response(report)


@api_view(["POST"])
def submit_for_review(request: Request, version_id: str) -> Response:
    tenant_id = _tenant(request)
    try:
        v = protocols.submit_for_review(
            tenant_id=str(tenant_id), version_id=version_id, actor=_actor(request)
        )
    except core.IllegalTransition as exc:
        return Response({"detail": str(exc)}, status=status.HTTP_409_CONFLICT)
    return Response(_version_summary(v))


@api_view(["POST"])
def approve(request: Request, version_id: str) -> Response:
    tenant_id = _tenant(request)
    try:
        v = protocols.approve(
            tenant_id=str(tenant_id), version_id=version_id, actor=_actor(request),
            role=request.data.get("role", "clinical"),
        )
    except (ValueError, core.IllegalTransition) as exc:
        return Response({"detail": str(exc)}, status=status.HTTP_409_CONFLICT)
    return Response(_version_summary(v))


@api_view(["POST"])
def deploy(request: Request, version_id: str) -> Response:
    tenant_id = _tenant(request)
    body = request.data
    try:
        d = protocols.deploy(
            tenant_id=str(tenant_id), version_id=version_id, mode=body.get("mode", "shadow"),
            rollout_percentage=int(body.get("rollout_percentage", 100)),
            target_scope=body.get("target_scope"), monitoring_plan=body.get("monitoring_plan"),
            actor=_actor(request),
        )
    except protocols.ActivationBlocked as exc:
        return Response({"detail": str(exc), "activation_blocked": True},
                        status=status.HTTP_422_UNPROCESSABLE_ENTITY)
    except core.SafetyViolation as exc:
        return Response({"detail": str(exc), "safety_violation": True},
                        status=status.HTTP_422_UNPROCESSABLE_ENTITY)
    return Response({
        "id": str(d.id), "version_id": str(d.version_id), "mode": d.mode,
        "status": d.status, "conflicts_suppressed": d.conflicts_suppressed,
        "rollback_to_version": d.rollback_to_version,
    }, status=status.HTTP_201_CREATED)


@api_view(["POST"])
def rollback(request: Request, deployment_id: str) -> Response:
    tenant_id = _tenant(request)
    try:
        r = protocols.rollback(
            tenant_id=str(tenant_id), deployment_id=deployment_id,
            reason=request.data.get("reason", "manual rollback"),
            automatic=bool(request.data.get("automatic", False)), actor=_actor(request),
        )
    except Deployment.DoesNotExist:
        return Response({"detail": "not found"}, status=status.HTTP_404_NOT_FOUND)
    return Response({"from_version": r.from_version, "to_version": r.to_version,
                     "automatic": r.automatic})


@api_view(["GET"])
def release_bundle(request: Request, version_id: str) -> Response:
    tenant_id = _tenant(request)
    try:
        bundle = protocols.build_release_bundle(tenant_id=str(tenant_id), version_id=version_id)
    except ProtocolVersion.DoesNotExist:
        return Response({"detail": "not found"}, status=status.HTTP_404_NOT_FOUND)
    return Response(bundle)


urlpatterns = [
    path("protocols", protocols_collection, name="protocols-collection"),
    path("protocols/<uuid:protocol_id>/versions", create_version, name="protocol-versions"),
    path("protocol-versions/<uuid:version_id>/test-cases", add_test_case, name="version-tests"),
    path("protocol-versions/<uuid:version_id>/simulate", simulate, name="version-simulate"),
    path("protocol-versions/<uuid:version_id>/impact", impact, name="version-impact"),
    path("protocol-versions/<uuid:version_id>/submit", submit_for_review, name="version-submit"),
    path("protocol-versions/<uuid:version_id>/approve", approve, name="version-approve"),
    path("protocol-versions/<uuid:version_id>/deploy", deploy, name="version-deploy"),
    path("protocol-versions/<uuid:version_id>/bundle", release_bundle, name="version-bundle"),
    path("deployments/<uuid:deployment_id>/rollback", rollback, name="deployment-rollback"),
]
