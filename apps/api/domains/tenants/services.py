"""Public service interface for the Tenants module (spec §7.4).

Other modules resolve tenant/site/specialty context ONLY through this interface.
"""
from __future__ import annotations

from .models import Organization


def get_active_organization(org_id: str) -> Organization | None:
    return Organization.objects.filter(id=org_id, is_active=True).first()
