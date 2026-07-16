"""Root URL configuration."""
from django.conf import settings
from django.http import JsonResponse
from django.urls import include, path


def healthz(_request):
    """Liveness probe. No PHI, no auth."""
    return JsonResponse({"status": "ok", "service": "clinara-api"})


urlpatterns = [
    path("healthz", healthz, name="healthz"),
    path("api/v1/", include("clinara.api_v1")),  # Phase 1 — Results Intelligence
    path("api/v1/", include("clinara.api_v1_protocols")),  # Phase 2 — Clinical Rule Studio
    path("api/v1/", include("clinara.api_v1_integrations")),  # Phase 3 — EHR Integration
    path("api/v1/", include("clinara.api_v1_refills")),  # Phase 4 — Refill Intelligence
    path("api/v1/", include("clinara.api_v1_messages")),  # Phase 5 — Message Intelligence
    path("api/v1/", include("clinara.api_v1_analytics")),  # Phase 6 — Analytics & Personalization
    path("api/v1/", include("clinara.api_v1_embedded")),  # Phase 8 — EHR-Embedded Surface
    path("api/v1/", include("clinara.api_v1_coding")),  # Phase 9 — Billing & Coding Intelligence
    path("api/v1/", include("clinara.api_v1_specialties")),  # Phase 10 — Specialty Protocol Breadth
    path("api/v1/", include("clinara.api_v1_retention")),  # Phase 11 — Data Lifecycle & Compliance
]

# EHR-embedded clinician surface — rendered inside the EHR after a SMART launch (Phase 8).
urlpatterns += [path("embedded/", include("clinara.embedded_surface"))]

# Clinician console — same-origin UI over the API. Mounted in DEBUG and wherever the
# deployment opts in via ENABLE_CONSOLE (e.g. the hosted Vercel surface). Sign-in is
# credentialed (username + password); see clinara.console.
if settings.DEBUG or getattr(settings, "ENABLE_CONSOLE", False):
    urlpatterns += [path("console/", include("clinara.console"))]

# Convenience: send the site root to the console so the deployed URL lands on sign-in.
if settings.DEBUG or getattr(settings, "ENABLE_CONSOLE", False):
    from django.views.generic.base import RedirectView

    urlpatterns += [path("", RedirectView.as_view(url="/console/", permanent=False))]
