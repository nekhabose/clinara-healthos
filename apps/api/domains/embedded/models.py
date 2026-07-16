"""EHR-embedded surface persistence (plan Phase 8 — closes G4).

Three tables model the SMART-on-FHIR EHR-launch handshake and identity bridge:

  * ``EhrConnection``   — the issuer→tenant *routing* table. One row per registered EHR FHIR
    endpoint; maps a launching ``iss`` to a tenant + the app's OAuth registration. It is
    resolved **before** any tenant context exists (the launch request is unauthenticated), so
    it is deliberately NOT under the per-tenant RLS policy — it is the bootstrap that yields
    the tenant. It holds only non-secret client identifiers/endpoints (the JWT verifier and
    any secret are injected at call time), so this is safe.
  * ``EhrLaunchSession`` — one row per launch attempt, keyed by an unguessable ``state``. It
    carries the CSRF ``state`` + OIDC ``nonce`` across the authorize→callback round-trip and,
    once bridged, the resolved user + patient context + hard expiry. Looked up by ``state``
    during the (still unauthenticated) callback, so it is also outside the RLS policy; every
    row still records its ``tenant_id`` and the service binds the tenant from it immediately.
  * ``EhrIdentityLink`` — maps an EHR clinician identity (``fhirUser``/``sub``) to a Clinara
    ``User`` within a tenant. Resolved only *after* the tenant is bound, so it IS RLS-scoped —
    tenant isolation of the identity bridge is enforced at the database.
"""
from __future__ import annotations

from django.db import models

from core.models import TenantScopedModel
from domains.identity.models import User


class EhrConnection(TenantScopedModel):
    """A registered EHR FHIR endpoint and the app's SMART registration against it."""

    issuer = models.CharField(max_length=512, unique=True)  # FHIR base URL (the launch ``iss``)
    vendor = models.CharField(max_length=32, default="epic")  # epic | athena | other
    client_id = models.CharField(max_length=255)
    redirect_uri = models.CharField(max_length=512)
    scopes = models.JSONField(default=list)  # e.g. ["openid", "fhirUser", "launch", ...]
    active = models.BooleanField(default=True, db_index=True)

    class Meta:
        indexes = [models.Index(fields=["issuer", "active"])]

    def __str__(self) -> str:
        return f"ehr-connection:{self.vendor}:{self.issuer}"


class LaunchStatus(models.TextChoices):
    PENDING = "pending", "Pending"      # authorize redirect issued, awaiting callback
    ACTIVE = "active", "Active"         # bridged to a Clinara session
    DENIED = "denied", "Denied"         # no identity link — refused
    EXPIRED = "expired", "Expired"      # past its hard expiry


class EhrLaunchSession(TenantScopedModel):
    connection = models.ForeignKey(
        EhrConnection, on_delete=models.CASCADE, related_name="launch_sessions"
    )
    state = models.CharField(max_length=64, unique=True, db_index=True)  # CSRF anti-forgery
    nonce = models.CharField(max_length=64)                              # OIDC id_token binding
    issuer = models.CharField(max_length=512)
    token_url = models.CharField(max_length=512, blank=True, default="")
    launch_token = models.CharField(max_length=512, blank=True, default="")  # opaque EHR launch
    status = models.CharField(
        max_length=12, choices=LaunchStatus.choices,
        default=LaunchStatus.PENDING, db_index=True,
    )
    user = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name="ehr_launches"
    )
    patient_context = models.CharField(max_length=128, blank=True, default="")
    encounter_context = models.CharField(max_length=128, blank=True, default="")
    expires_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [models.Index(fields=["tenant_id", "status"])]
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"ehr-launch:{self.status}"


class EhrIdentityLink(TenantScopedModel):
    """Maps an EHR clinician identity to a Clinara user (tenant-scoped, RLS-enforced)."""

    connection = models.ForeignKey(
        EhrConnection, on_delete=models.CASCADE, related_name="identity_links"
    )
    subject = models.CharField(max_length=255, db_index=True)  # fhirUser reference or OIDC sub
    user = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="ehr_identity_links"
    )
    active = models.BooleanField(default=True, db_index=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["connection", "subject"], name="uniq_connection_subject"
            )
        ]
        indexes = [models.Index(fields=["tenant_id", "subject"])]

    def __str__(self) -> str:
        return f"ehr-identity:{self.subject}"
