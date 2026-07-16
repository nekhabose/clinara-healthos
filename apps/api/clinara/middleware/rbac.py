"""RBAC enforcement middleware (spec §10.2).

Gates every ``/api/v1/*`` route by the authenticated user's role using the single capability
policy in ``clinara.rbac``. Runs after Django's ``AuthenticationMiddleware`` so ``request.user``
is resolved (the console uses session auth, shared with DRF's ``SessionAuthentication``).

- A request with no authenticated user is left alone so the view's ``IsAuthenticated`` returns
  the usual 401 (RBAC does not leak whether a resource exists to anonymous callers).
- An authenticated user whose role lacks the required capability gets a 403 with no resource
  data — the denial is fail-closed (unknown role ⇒ no capabilities).
- Public API segments (SMART launch / embedded surface) are skipped; they run under their own
  session model.

This is defense-in-depth over the per-view permissions: one choke point that every API route
passes through, so a newly added view cannot accidentally ship without role enforcement.
"""
from __future__ import annotations

from django.http import JsonResponse
from django.utils.deprecation import MiddlewareMixin

from clinara.rbac import capabilities_for, required_capability


class RbacMiddleware(MiddlewareMixin):
    def process_request(self, request):
        capability = required_capability(request.path)
        if capability is None:
            return None  # not an RBAC-gated API route

        user = getattr(request, "user", None)
        if user is None or not getattr(user, "is_authenticated", False):
            return None  # unauthenticated -> let the view's IsAuthenticated return 401

        if capability in capabilities_for(getattr(user, "role", None)):
            return None  # authorized

        return JsonResponse(
            {
                "detail": "forbidden: your role does not have access to this resource",
                "required_capability": capability,
            },
            status=403,
        )
