"""API v1 — EHR-Embedded Clinician Surface (plan Phase 8; closes G4 + G5; spec §6.10.2).

The SMART-on-FHIR EHR-launch endpoints and the chart-context panel. The two launch endpoints
are the *only* unauthenticated surface here (the EHR, not a Clinara session, initiates them);
they establish the session by bridging the EHR identity, after which the embedded surface and
context panel are ordinary tenant-scoped, authenticated calls.

  * ``GET  /api/v1/smart/launch``      — EHR launch → 302 to the EHR authorize endpoint.
  * ``GET  /api/v1/smart/callback``    — authorize redirect back → bridge identity, sign in,
                                          302 to the embedded surface. No separate login.
  * ``GET  /api/v1/embedded/session``  — the current embedded session identity (whoami).
  * ``GET  /api/v1/embedded/context/{workflow_id}`` — the chart-context panel (G5).
  * ``POST /api/v1/embedded/connections`` and ``…/{id}/identities`` — admin registration.

Vendor/protocol quirks stay in the SDK + adapters; this layer only translates HTTP ↔ service.
"""
from __future__ import annotations

from django.contrib.auth import login
from django.shortcuts import redirect
from django.urls import path
from django.views.decorators.clickjacking import xframe_options_exempt
from rest_framework import status
from rest_framework.decorators import (
    api_view,
    authentication_classes,
    permission_classes,
)
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response

from domains.context.services import SnapshotNotFound, chart_context_panel
from domains.embedded import adapters
from domains.embedded import services as embedded

_MODEL_BACKEND = "django.contrib.auth.backends.ModelBackend"


def _tenant(request: Request) -> str | None:
    return getattr(request.user, "organization_id", None)


def _actor(request: Request) -> str:
    return getattr(request.user, "username", "unknown")


# ---- SMART EHR launch (unauthenticated — EHR-initiated) ----

@api_view(["GET"])
@authentication_classes([])
@permission_classes([AllowAny])
def smart_launch(request: Request) -> Response:
    """Begin an EHR launch: resolve issuer→tenant, then redirect to the EHR authorize URL."""
    iss = request.query_params.get("iss", "")
    launch = request.query_params.get("launch", "")
    if not iss or not launch:
        return Response({"detail": "iss and launch are required"},
                        status=status.HTTP_400_BAD_REQUEST)
    try:
        result = embedded.begin_launch(
            issuer=iss, launch=launch, transport=adapters.launch_transport())
    except embedded.UnknownIssuerError:
        return Response({"detail": "unrecognized issuer"}, status=status.HTTP_403_FORBIDDEN)
    return redirect(result["authorize_url"])


@api_view(["GET"])
@authentication_classes([])
@permission_classes([AllowAny])
def smart_callback(request: Request) -> Response:
    """Complete the launch: exchange the code, bridge identity, sign in, go to the surface.

    A successful bridge establishes the Django session directly (no Clinara sign-in screen) and
    caps its lifetime at the EHR token's — so the embedded session expires with the EHR session.
    """
    state = request.query_params.get("state", "")
    code = request.query_params.get("code", "")
    if not state or not code:
        return Response({"detail": "state and code are required"},
                        status=status.HTTP_400_BAD_REQUEST)
    try:
        result = embedded.complete_launch(
            state=state, code=code, transport=adapters.launch_transport(),
            verifier=adapters.launch_verifier())
    except embedded.LaunchStateError:
        return Response({"detail": "invalid or expired launch"},
                        status=status.HTTP_400_BAD_REQUEST)
    except embedded.IdentityBridgeDenied:
        return Response({"detail": "EHR identity is not linked to a Clinara user"},
                        status=status.HTTP_403_FORBIDDEN)

    from domains.identity.models import User
    user = User.objects.get(id=result["user_id"])
    login(request, user, backend=_MODEL_BACKEND)
    # Cap the session at the EHR token lifetime — it cannot outlive the EHR session.
    request.session.set_expiry(result["expires_in"])
    request.session["ehr_launch_session_id"] = result["session_id"]
    request.session["ehr_patient_context"] = result["patient"] or ""
    return redirect(f"/embedded/?patient={result['patient'] or ''}")


# ---- embedded session + chart-context panel (authenticated) ----

@api_view(["GET"])
def embedded_session(request: Request) -> Response:
    """The current embedded session identity + live launch context (whoami for the surface)."""
    tenant_id = _tenant(request)
    if not tenant_id:
        return Response({"detail": "no tenant context"}, status=status.HTTP_403_FORBIDDEN)
    session_id = request.session.get("ehr_launch_session_id")
    live = None
    if session_id:
        s = embedded.get_live_session(tenant_id=str(tenant_id), session_id=session_id)
        if s is not None:
            live = {"session_id": str(s.id), "patient": s.patient_context or None,
                    "encounter": s.encounter_context or None,
                    "vendor": s.connection.vendor, "expires_at": s.expires_at.isoformat()}
    return Response({
        "authenticated": True,
        "username": _actor(request),
        "role": getattr(request.user, "role", None),
        "tenant": str(tenant_id),
        "embedded": live is not None,
        "launch": live,
    })


@api_view(["GET"])
def chart_context(request: Request, workflow_id: str) -> Response:
    """The clinician-facing chart-context panel for an item under review (G5)."""
    tenant_id = _tenant(request)
    if not tenant_id:
        return Response({"detail": "no tenant context"}, status=status.HTTP_403_FORBIDDEN)
    try:
        panel = chart_context_panel(tenant_id=str(tenant_id), workflow_id=str(workflow_id))
    except SnapshotNotFound:
        return Response({"detail": "no context snapshot"}, status=status.HTTP_404_NOT_FOUND)
    return Response(panel)


# ---- admin registration (tenant admin / integration engineer) ----

@api_view(["POST"])
def register_connection(request: Request) -> Response:
    tenant_id = _tenant(request)
    if not tenant_id:
        return Response({"detail": "no tenant context"}, status=status.HTTP_403_FORBIDDEN)
    b = request.data
    conn = embedded.register_connection(
        tenant_id=str(tenant_id), issuer=b["issuer"], client_id=b["client_id"],
        redirect_uri=b["redirect_uri"], vendor=b.get("vendor", "epic"),
        scopes=b.get("scopes"), actor=_actor(request))
    return Response({"id": str(conn.id), "issuer": conn.issuer, "vendor": conn.vendor},
                    status=status.HTTP_201_CREATED)


@api_view(["POST"])
def link_identity(request: Request, connection_id: str) -> Response:
    tenant_id = _tenant(request)
    if not tenant_id:
        return Response({"detail": "no tenant context"}, status=status.HTTP_403_FORBIDDEN)
    b = request.data
    link = embedded.link_identity(
        tenant_id=str(tenant_id), connection_id=str(connection_id), subject=b["subject"],
        user_id=b["user_id"], actor=_actor(request))
    return Response({"id": str(link.id), "subject": link.subject},
                    status=status.HTTP_201_CREATED)


# The embedded surface is meant to render inside the EHR's iframe/app frame.
smart_launch = xframe_options_exempt(smart_launch)
smart_callback = xframe_options_exempt(smart_callback)


urlpatterns = [
    path("smart/launch", smart_launch, name="smart-launch"),
    path("smart/callback", smart_callback, name="smart-callback"),
    path("embedded/session", embedded_session, name="embedded-session"),
    path("embedded/context/<uuid:workflow_id>", chart_context, name="embedded-context"),
    path("embedded/connections", register_connection, name="embedded-connections"),
    path("embedded/connections/<uuid:connection_id>/identities", link_identity,
         name="embedded-link-identity"),
]
