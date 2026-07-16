"""Clinician console — a same-origin operator/clinician UI over the /api/v1 surface.

Served in any environment where ``ENABLE_CONSOLE`` is set (see ``clinara.urls``). Because it
is served from the same origin as the API, DRF SessionAuthentication + CSRF work with no CORS.
``/console/login`` authenticates a real Clinara account (username + password) against the
Django auth backend and establishes the audited session; every action the console drives is
attributed to that account.
"""
from __future__ import annotations

from django.contrib.auth import authenticate, login, logout
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.urls import path
from django.views.decorators.http import require_POST


def console(request):
    """Serve the single-page console (sign-in screen when unauthenticated)."""
    return render(request, "console.html", {"user": request.user})


@require_POST
def console_login(request):
    """Authenticate a real Clinara account by username + password."""
    username = (request.POST.get("username") or "").strip()
    password = request.POST.get("password") or ""
    user = authenticate(request, username=username, password=password)
    if user is None:
        return render(
            request,
            "console.html",
            {
                "user": request.user,
                "login_error": "Incorrect username or password.",
                "login_username": username,
            },
            status=401,
        )
    login(request, user)
    return redirect("console")


@require_POST
def console_logout(request):
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
    path("login", console_login, name="console-login"),
    path("logout", console_logout, name="console-logout"),
    path("whoami", whoami, name="console-whoami"),
]
