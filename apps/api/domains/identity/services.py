"""Public service interface for the Identity module (spec §7.4)."""
from __future__ import annotations

from .models import User
from .roles import PHI_ACCESS_ROLES


def can_access_phi(user: User) -> bool:
    """Whether a user's role permits PHI access (drives PHI-access audit + authorization)."""
    return user.role in PHI_ACCESS_ROLES
