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

# Demo console — dev/demo only (same-origin UI over the API). Never mounted in production.
if settings.DEBUG:
    urlpatterns += [path("console/", include("clinara.console"))]
