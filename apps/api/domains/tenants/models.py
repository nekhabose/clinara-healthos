"""Tenancy hierarchy (spec §8.1 Tenancy).

Organization → Site → Department → Practice, plus Specialty and CareTeam. The
Organization is the tenant boundary; ``tenant_id`` on every clinical row equals the
owning Organization's id, which is what RLS enforces.
"""
from __future__ import annotations

from django.db import models

from core.models import TimeStampedModel


class Organization(TimeStampedModel):
    """The tenant. Top of the hierarchy and the RLS isolation boundary."""

    name = models.CharField(max_length=255)
    slug = models.SlugField(unique=True)
    is_active = models.BooleanField(default=True)
    # Tenant-configurable data-retention / policy live in a related config table (Phase 1+).

    def __str__(self) -> str:
        return self.name


class Site(TimeStampedModel):
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="sites")
    name = models.CharField(max_length=255)

    def __str__(self) -> str:
        return self.name


class Department(TimeStampedModel):
    site = models.ForeignKey(Site, on_delete=models.CASCADE, related_name="departments")
    name = models.CharField(max_length=255)


class Practice(TimeStampedModel):
    department = models.ForeignKey(
        Department, on_delete=models.CASCADE, related_name="practices", null=True, blank=True
    )
    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="practices"
    )
    name = models.CharField(max_length=255)


class Specialty(TimeStampedModel):
    """Reference list of specialties used for protocol scoping (spec §6.5.3)."""

    key = models.SlugField(unique=True)  # e.g. "endocrinology"
    name = models.CharField(max_length=255)


class CareTeam(TimeStampedModel):
    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="care_teams"
    )
    name = models.CharField(max_length=255)
