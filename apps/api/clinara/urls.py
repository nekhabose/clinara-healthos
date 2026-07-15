"""Root URL configuration."""
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
]
