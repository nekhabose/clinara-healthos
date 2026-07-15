"""Identity & RBAC (spec §8.1 Tenancy, §10.2).

Custom user tied to an Organization (the tenant). SSO/MFA are enforced at the IdP and
gateway; this model holds the authorization surface (role) and the tenant anchor used by
TenantContextMiddleware to set the RLS session var.
"""
from __future__ import annotations

import uuid

from django.contrib.auth.models import AbstractUser
from django.db import models

from .roles import ROLE_CHOICES


class User(AbstractUser):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # Tenant anchor. Read by TenantContextMiddleware -> app.current_tenant (RLS).
    organization_id = models.UUIDField(null=True, blank=True, db_index=True)

    role = models.CharField(max_length=40, choices=ROLE_CHOICES, null=True, blank=True)

    # SSO linkage (SAML/OIDC subject); local passwords disabled in production.
    sso_subject = models.CharField(max_length=255, null=True, blank=True, db_index=True)
    mfa_enrolled = models.BooleanField(default=False)

    def __str__(self) -> str:
        return f"{self.username} ({self.role})"


class PractitionerProfile(models.Model):
    """Clinician/nurse profile linked to a user; preferences live in a later phase."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="practitioner")
    npi = models.CharField(max_length=20, null=True, blank=True)
    display_name = models.CharField(max_length=255)
    specialties = models.JSONField(default=list)  # list of Specialty keys

    def __str__(self) -> str:
        return self.display_name


class BreakGlassGrantRecord(models.Model):
    """Time-boxed emergency access grant (GA hardening — spec §10.2).

    Break-glass is always audited (grant, use, revoke) and hard-expires. Validation lives in
    the pure ``identity.breakglass`` core; this row is the persisted grant plus its lifecycle
    timestamps. ``expires_at`` is stamped at grant time so an expiry check needs no arithmetic.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    responder = models.CharField(max_length=200, db_index=True)
    reason = models.TextField()
    granted_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(db_index=True)
    revoked = models.BooleanField(default=False, db_index=True)
    revoked_by = models.CharField(max_length=200, blank=True, default="")
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-granted_at"]

    def __str__(self) -> str:
        return f"break-glass:{self.responder}"
