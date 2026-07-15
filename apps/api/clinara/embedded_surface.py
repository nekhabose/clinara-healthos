"""EHR-embedded clinician surface (plan Phase 8 — G4 workstream 2).

The review surface rendered *inside* the EHR's app frame after a SMART launch. It is a thin
single-page shell over the authenticated ``/api/v1`` surface (the same audited service layer
the standalone console uses): it reads the bridged session from ``/api/v1/embedded/session``,
lists the clinician's review queue, and shows the chart-context panel
(``/api/v1/embedded/context/{id}``) beside the item under review — so there is no chart digging
and no separate login.

``xframe_options_exempt`` lets it render in the EHR iframe; auth is enforced by the API calls
it makes (the session established by the SMART callback), not by the shell itself.
"""
from __future__ import annotations

from django.shortcuts import render
from django.urls import path
from django.views.decorators.clickjacking import xframe_options_exempt


@xframe_options_exempt
def embedded_surface(request):
    """Serve the embedded single-page review surface."""
    return render(request, "embedded.html", {"patient": request.GET.get("patient", "")})


urlpatterns = [
    path("", embedded_surface, name="embedded-surface"),
]
