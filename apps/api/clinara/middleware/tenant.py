"""Tenant context middleware.

Resolves the tenant for each request and pins it into a context variable AND the
PostgreSQL session (``SET app.current_tenant``) so Row-Level Security policies can
enforce isolation at the database layer — defense in depth beyond app-layer filtering
(plan §1.2). A request with no resolvable tenant gets NULL, which RLS policies treat as
"see nothing".
"""
from __future__ import annotations

import contextvars

from django.db import connection
from django.utils.deprecation import MiddlewareMixin

# Readable anywhere in the request lifecycle (services, serializers, tasks).
current_tenant_id: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "current_tenant_id", default=None
)


def set_db_tenant(tenant_id: str | None) -> None:
    """Pin the tenant on the DB session for RLS. Parameterized to avoid injection.

    PostgreSQL-only: RLS and ``set_config`` do not exist on other backends (e.g. the SQLite
    test DB), so this is a no-op there. App-layer tenant filtering still applies everywhere;
    RLS is the production-Postgres defense-in-depth layer.
    """
    if connection.vendor != "postgresql":
        return
    # ``tenant_id`` may arrive as a ``uuid.UUID`` (User.organization_id is a UUIDField), which
    # psycopg adapts to a Postgres ``uuid`` param — set_config() only accepts ``text``. Cast to
    # the canonical hyphenated string so the value matches the RLS policy's ``tenant_id::text``.
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT set_config('app.current_tenant', %s, false)",
            [str(tenant_id) if tenant_id else ""],
        )


class TenantContextMiddleware(MiddlewareMixin):
    def process_request(self, request) -> None:
        tenant_id = self._resolve_tenant(request)
        current_tenant_id.set(tenant_id)
        set_db_tenant(tenant_id)

    @staticmethod
    def _resolve_tenant(request) -> str | None:
        # Phase 0: derive from the authenticated user's org membership.
        # Later phases add SMART-on-FHIR launch context and integration-gateway resolution.
        user = getattr(request, "user", None)
        if user is not None and getattr(user, "is_authenticated", False):
            return getattr(user, "organization_id", None)
        return None
