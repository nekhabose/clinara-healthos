"""Demo console — a same-origin operator/clinician UI over the /api/v1 surface.

Dev/demo only (guarded by ``DEBUG``). Because it is served from the same origin as the API,
DRF SessionAuthentication + CSRF work with no CORS. ``/console/login`` logs in one of the
seeded demo users so the console can drive the real, audited service layer end to end.
"""
from __future__ import annotations

from django.conf import settings
from django.contrib.auth import authenticate, login, logout
from django.http import HttpResponseForbidden, JsonResponse
from django.shortcuts import redirect, render
from django.urls import path
from django.views.decorators.http import require_POST

from core.management.commands.seed_demo import DEMO_PASSWORD


def console(request):
    """Serve the single-page console."""
    return render(request, "console.html", {"user": request.user})


@require_POST
def demo_login(request):
    """Log in a seeded demo user by username (dev only)."""
    if not settings.DEBUG:
        return HttpResponseForbidden("disabled")
    username = request.POST.get("username", "clinician")
    user = authenticate(request, username=username, password=DEMO_PASSWORD)
    if user is None:
        return JsonResponse({"detail": "unknown demo user — run seed_demo"}, status=400)
    login(request, user)
    return redirect("console")


@require_POST
def demo_logout(request):
    """End the session and return to the sign-in screen."""
    logout(request)
    return redirect("console")


def whoami(request):
    u = request.user
    return JsonResponse({
        "authenticated": u.is_authenticated,
        "username": getattr(u, "username", None),
        "role": getattr(u, "role", None),
        "tenant": str(getattr(u, "organization_id", "") or ""),
    })


urlpatterns = [
    path("", console, name="console"),
    path("login", demo_login, name="console-login"),
    path("logout", demo_logout, name="console-logout"),
    path("whoami", whoami, name="console-whoami"),
]
