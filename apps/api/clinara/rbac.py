"""Role-based access control (spec §10.2) — the single source of truth.

Maps each RBAC role to the capabilities it holds, and each API surface (the first path
segment under ``/api/v1/``) to the capability required to use it. Enforced server-side by
``clinara.middleware.rbac.RbacMiddleware`` on every ``/api/v1/*`` route, and mirrored to the
console navigation via ``/console/whoami`` so a user only sees the surfaces their role may act
on. Roles/capabilities are data here so the policy is auditable in one place, the same posture
as the rest of the platform.

The policy (the recommended matrix):

    surface (capability) │ clinician │ nurse │ reviewer │ programmer │ analyst │ admin
    ─────────────────────┼───────────┼───────┼──────────┼────────────┼─────────┼──────
    Results/Inbox        │     ✓     │   ✓   │    ✓     │            │         │  ✓
    Patient Messages     │     ✓     │   ✓   │    ✓     │            │         │  ✓
    Prescriptions        │     ✓     │   ✓   │    ✓     │            │         │  ✓
    Coding (billing)     │     ✓     │       │    ✓     │            │         │  ✓
    Protocols/Specialties│           │       │    ✓     │     ✓      │         │  ✓
    Analytics            │           │       │          │            │    ✓    │  ✓
    Retention/Integrations           │       │          │            │         │  ✓

PHI never reaches the programmer or analyst roles (consistent with
``domains.identity.roles.PHI_ACCESS_ROLES``).
"""
from __future__ import annotations

from clinara_shared_types import Role

# ---- Capabilities ----
CAP_RESULTS = "results"
CAP_MESSAGES = "messages"
CAP_PRESCRIPTIONS = "prescriptions"
CAP_CODING = "coding"
CAP_PROTOCOLS = "protocols"
CAP_ANALYTICS = "analytics"
CAP_ADMIN = "admin"

ALL_CAPABILITIES = frozenset(
    {
        CAP_RESULTS,
        CAP_MESSAGES,
        CAP_PRESCRIPTIONS,
        CAP_CODING,
        CAP_PROTOCOLS,
        CAP_ANALYTICS,
        CAP_ADMIN,
    }
)

# ---- Role -> capabilities ----
ROLE_CAPABILITIES: dict[str, frozenset[str]] = {
    Role.PLATFORM_ADMIN.value: ALL_CAPABILITIES,
    Role.TENANT_ADMIN.value: ALL_CAPABILITIES,
    Role.CLINICIAN.value: frozenset(
        {CAP_RESULTS, CAP_MESSAGES, CAP_PRESCRIPTIONS, CAP_CODING}
    ),
    Role.NURSE.value: frozenset({CAP_RESULTS, CAP_MESSAGES, CAP_PRESCRIPTIONS}),
    Role.CLINICAL_REVIEWER.value: frozenset(
        {CAP_RESULTS, CAP_MESSAGES, CAP_PRESCRIPTIONS, CAP_CODING, CAP_PROTOCOLS}
    ),
    Role.CLINICAL_PROGRAMMER.value: frozenset({CAP_PROTOCOLS}),
    Role.OPERATIONS_ANALYST.value: frozenset({CAP_ANALYTICS}),
}

# ---- API surface (first path segment under /api/v1/) -> required capability ----
# Every segment served by clinara.api_v1* is mapped explicitly; add new endpoint groups here.
SEGMENT_CAPABILITY: dict[str, str] = {
    "results": CAP_RESULTS,
    "workflows": CAP_RESULTS,  # incl. approve/override/escalate + write-back/release (clinical)
    "messages": CAP_MESSAGES,
    "refills": CAP_PRESCRIPTIONS,
    "coding": CAP_CODING,
    "protocols": CAP_PROTOCOLS,
    "protocol": CAP_PROTOCOLS,
    "deployments": CAP_PROTOCOLS,
    "specialties": CAP_PROTOCOLS,
    "analytics": CAP_ANALYTICS,
    "feedback": CAP_ANALYTICS,
    "retention": CAP_ADMIN,
    "integrations": CAP_ADMIN,
    "outbound": CAP_ADMIN,
    "delivery": CAP_ADMIN,
    "dead-letters": CAP_ADMIN,
}

# Public API segments run under their own session model (SMART launch / EHR-embedded surface);
# RBAC by Clinara role does not apply to them.
PUBLIC_SEGMENTS = frozenset({"embedded", "smart"})

_API_PREFIX = "/api/v1/"


def capabilities_for(role: str | None) -> frozenset[str]:
    """Capabilities granted to a role (empty for an unknown/None role — fail closed)."""
    return ROLE_CAPABILITIES.get(role or "", frozenset())


def required_capability(path: str) -> str | None:
    """Capability required to call an ``/api/v1/`` path.

    Returns ``None`` when the path is not an RBAC-gated API route (non-``/api/v1/``, a public
    segment, or a segment with no mapping — in which case the view's own ``IsAuthenticated``
    still applies). New ``/api/v1`` segments must be added to ``SEGMENT_CAPABILITY``.
    """
    if not path.startswith(_API_PREFIX):
        return None
    segment = path[len(_API_PREFIX) :].split("/", 1)[0]
    if segment in PUBLIC_SEGMENTS:
        return None
    return SEGMENT_CAPABILITY.get(segment)
