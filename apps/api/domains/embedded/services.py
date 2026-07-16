"""EHR-embedded surface service interface (plan Phase 8 — closes G4).

The single entry point for the SMART-on-FHIR EHR launch and identity bridge. Guarantees:

  * **Identity bridge preserves isolation** — a launch is only completed if the EHR clinician
    identity (``fhirUser``/``sub``) resolves to a Clinara ``User`` via an ``EhrIdentityLink``
    *within the issuer's tenant*. No link ⇒ the launch is refused (fail-closed), never bridged
    to a default account. Every launch — bridged or denied — is audited and event-published.
  * **No separate login** — the successful callback yields the resolved user; the API layer
    establishes the Django session directly, so the clinician never sees a Clinara sign-in.
  * **Session expires with the EHR session** — ``expires_at`` is stamped from the EHR token's
    ``expires_in``, so the bridged session cannot outlive the EHR's.

The SMART protocol (discovery, authorize URL, token exchange, id_token validation) is the pure
SDK in ``clinara_integration_sdk.smart_launch``; the HTTP transport and JWT verifier are
injected, so the whole flow runs against a fake EHR in tests and a live Epic/Athena endpoint
by configuration alone — the same injection discipline as Phase 7.
"""
from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import datetime, timedelta

from clinara_integration_sdk import (
    HttpTransport,
    SmartEndpoints,
    UrllibTransport,
    Verifier,
    build_authorize_url,
    discover_endpoints,
    exchange_code,
)
from clinara_shared_types import EventType
from django.db import transaction
from django.utils import timezone

from clinara.middleware.phi_safe_logging import correlation_id as _correlation_id
from clinara.middleware.tenant import current_tenant_id, set_db_tenant
from core.outbox import publish_event
from domains.audit import services as audit

from . import core
from .models import EhrConnection, EhrIdentityLink, EhrLaunchSession, LaunchStatus


class UnknownIssuerError(RuntimeError):
    """The launching ``iss`` is not a registered, active EHR connection."""


class LaunchStateError(RuntimeError):
    """The callback ``state`` is unknown, already used, or stale."""


class IdentityBridgeDenied(RuntimeError):
    """The EHR clinician identity has no active link to a Clinara user in this tenant."""


def _bind(tenant_id: str) -> None:
    """Pin tenant + a fresh correlation id for RLS and audit within this call."""
    current_tenant_id.set(str(tenant_id))
    if not _correlation_id.get():
        _correlation_id.set(str(uuid.uuid4()))
    set_db_tenant(str(tenant_id))


# ---- registration (tenant admin / integration engineer) ----

def register_connection(
    *, tenant_id: str, issuer: str, client_id: str, redirect_uri: str,
    vendor: str = "epic", scopes: list[str] | None = None, actor: str = "system",
) -> EhrConnection:
    """Register (or update) an EHR FHIR endpoint for a tenant. Audited."""
    _bind(tenant_id)
    with transaction.atomic():
        conn, created = EhrConnection.objects.update_or_create(
            issuer=issuer,
            defaults={
                "tenant_id": tenant_id, "client_id": client_id, "vendor": vendor,
                "redirect_uri": redirect_uri,
                "scopes": scopes or ["openid", "fhirUser", "launch"],
                "active": True,
            },
        )
        audit.record(actor=actor, action="ehr_connection_registered",
                     resource=f"ehr_connection:{conn.id}", reason=vendor,
                     after_state={"issuer": issuer, "created": created})
    return conn


def link_identity(
    *, tenant_id: str, connection_id: str, subject: str, user_id: str, actor: str = "system",
) -> EhrIdentityLink:
    """Link an EHR clinician identity (``fhirUser``/``sub``) to a Clinara user. Audited."""
    _bind(tenant_id)
    with transaction.atomic():
        link, created = EhrIdentityLink.objects.update_or_create(
            connection_id=connection_id, subject=subject,
            defaults={"tenant_id": tenant_id, "user_id": user_id, "active": True},
        )
        audit.record(actor=actor, action="ehr_identity_linked",
                     resource=f"ehr_identity:{link.id}", reason=subject,
                     after_state={"user_id": str(user_id), "created": created})
    return link


# ---- SMART EHR launch (step 1-3) ----

def begin_launch(
    *, issuer: str, launch: str, transport: HttpTransport | None = None,
    state_factory: Callable[[], str] | None = None,
    nonce_factory: Callable[[], str] | None = None,
) -> dict:
    """Resolve the issuer→tenant, discover endpoints, and mint the authorize redirect.

    Returns ``{"authorize_url", "state", "session_id", "tenant_id"}``. Raises
    ``UnknownIssuerError`` if the launching EHR is not a registered active connection — an
    unrecognized ``iss`` can never start a session.
    """
    transport = transport or UrllibTransport()
    state_factory = state_factory or (lambda: uuid.uuid4().hex)
    nonce_factory = nonce_factory or (lambda: uuid.uuid4().hex)

    conn = EhrConnection.objects.filter(issuer=issuer, active=True).first()
    if conn is None:
        raise UnknownIssuerError("unrecognized issuer")
    tenant_id = str(conn.tenant_id)
    _bind(tenant_id)

    endpoints = discover_endpoints(iss=issuer, transport=transport)
    cfg = core.launch_config(client_id=conn.client_id, redirect_uri=conn.redirect_uri,
                             scopes=conn.scopes)
    state, nonce = state_factory(), nonce_factory()
    authorize_url = build_authorize_url(
        config=cfg, endpoints=endpoints, iss=issuer, launch=launch, state=state, nonce=nonce)

    with transaction.atomic():
        session = EhrLaunchSession.objects.create(
            tenant_id=tenant_id, connection=conn, state=state, nonce=nonce, issuer=issuer,
            token_url=endpoints.token_url, launch_token=launch, status=LaunchStatus.PENDING,
        )
        audit.record(actor="system", action="ehr_launch_begin",
                     resource=f"ehr_launch:{session.id}", reason=conn.vendor)
    return {"authorize_url": authorize_url, "state": state,
            "session_id": str(session.id), "tenant_id": tenant_id}


# ---- SMART callback: exchange + identity bridge (step 4-6) ----

def complete_launch(
    *, state: str, code: str, transport: HttpTransport | None = None,
    verifier: Verifier, now: datetime | None = None,
) -> dict:
    """Exchange the code, validate the id_token, and bridge to a Clinara user.

    Returns the resolved session identity for the API layer to establish a session:
    ``{"session_id", "user_id", "username", "tenant_id", "patient", "encounter",
    "expires_in", "expires_at"}``. Raises ``LaunchStateError`` for an unknown/used/stale
    ``state``, and ``IdentityBridgeDenied`` (fail-closed) when the EHR identity has no link.
    """
    transport = transport or UrllibTransport()
    now = now or timezone.now()

    session = EhrLaunchSession.objects.filter(state=state).first()
    if session is None:
        raise LaunchStateError("unknown launch state")
    tenant_id = str(session.tenant_id)
    _bind(tenant_id)

    if session.status != LaunchStatus.PENDING:
        raise LaunchStateError("launch state already used")
    if now - session.created_at > timedelta(seconds=core.PENDING_LAUNCH_TTL_SECONDS):
        _mark_denied(session, reason="stale launch state")
        raise LaunchStateError("launch state expired")

    cfg = core.launch_config(
        client_id=session.connection.client_id, redirect_uri=session.connection.redirect_uri,
        scopes=session.connection.scopes)
    endpoints = SmartEndpoints(authorize_url="", token_url=session.token_url)
    ctx = exchange_code(
        config=cfg, endpoints=endpoints, code=code, transport=transport, verifier=verifier,
        now_epoch=now.timestamp(), iss=session.issuer, expected_nonce=session.nonce)

    subject = ctx.subject
    link = EhrIdentityLink.objects.filter(
        tenant_id=tenant_id, connection=session.connection, subject=subject, active=True,
    ).select_related("user").first()
    if link is None:
        _mark_denied(session, reason="no identity link", subject=subject)
        raise IdentityBridgeDenied("EHR identity is not linked to a Clinara user")

    user = link.user
    expires_at = now + timedelta(seconds=max(1, ctx.expires_in))
    with transaction.atomic():
        session.status = LaunchStatus.ACTIVE
        session.user = user
        session.patient_context = ctx.patient or ""
        session.encounter_context = ctx.encounter or ""
        session.expires_at = expires_at
        session.save(update_fields=["status", "user", "patient_context", "encounter_context",
                                    "expires_at", "updated_at"])
        audit.record(actor=user.username, action="ehr_launch",
                     resource=f"ehr_launch:{session.id}", reason=session.connection.vendor,
                     after_state={"patient": bool(ctx.patient),
                                  "expires_at": expires_at.isoformat()})
        publish_event(
            event_type=EventType.EHR_LAUNCHED.value,
            idempotency_key=f"ehr-launched:{session.id}",
            payload={"session_id": str(session.id), "user_id": str(user.id),
                     "vendor": session.connection.vendor, "has_patient": bool(ctx.patient)},
        )
    return {
        "session_id": str(session.id), "user_id": str(user.id), "username": user.username,
        "tenant_id": tenant_id, "patient": ctx.patient, "encounter": ctx.encounter,
        "expires_in": max(1, ctx.expires_in), "expires_at": expires_at.isoformat(),
    }


def _mark_denied(session: EhrLaunchSession, *, reason: str, subject: str = "") -> None:
    """Record + audit a refused launch. Its own committed transaction so the refusal survives."""
    with transaction.atomic():
        session.status = LaunchStatus.DENIED
        session.save(update_fields=["status", "updated_at"])
        audit.record(actor="system", action="ehr_launch_denied",
                     resource=f"ehr_launch:{session.id}", reason=reason)
        publish_event(
            event_type=EventType.EHR_LAUNCH_DENIED.value,
            idempotency_key=f"ehr-launch-denied:{session.id}",
            payload={"session_id": str(session.id), "reason": reason, "subject": subject},
        )


# ---- session resolution (surface + context authorization) ----

def get_live_session(*, tenant_id: str, session_id: str, now: datetime | None = None):
    """Return the launch session if it is still live (ACTIVE + unexpired), else ``None``.

    Also transitions a lapsed session to EXPIRED so the state reflects reality (idempotent).
    """
    now = now or timezone.now()
    _bind(tenant_id)
    session = EhrLaunchSession.objects.filter(id=session_id, tenant_id=tenant_id).first()
    if session is None:
        return None
    if core.session_is_live(status=session.status, expires_at=session.expires_at, now=now):
        return session
    if session.status == LaunchStatus.ACTIVE:  # was active, now lapsed → record expiry
        with transaction.atomic():
            session.status = LaunchStatus.EXPIRED
            session.save(update_fields=["status", "updated_at"])
    return None


__all__ = [
    "register_connection", "link_identity", "begin_launch", "complete_launch",
    "get_live_session", "UnknownIssuerError", "LaunchStateError", "IdentityBridgeDenied",
]
