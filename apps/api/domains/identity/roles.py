"""RBAC role catalog (spec §10.2). Mirrors clinara_shared_types.Role for DB use."""
from __future__ import annotations

from clinara_shared_types import Role

ROLE_CHOICES = [(r.value, r.name.replace("_", " ").title()) for r in Role]

# Roles permitted to author/deploy clinical logic (used by protocols module, Phase 2).
CLINICAL_AUTHORING_ROLES = {Role.CLINICAL_PROGRAMMER.value, Role.CLINICAL_REVIEWER.value}

# Roles that may view PHI (drives PHI-access audit).
PHI_ACCESS_ROLES = {
    Role.CLINICIAN.value,
    Role.NURSE.value,
    Role.CLINICAL_REVIEWER.value,
}
