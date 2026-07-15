"""Root URL configuration."""
from django.http import JsonResponse
from django.urls import path


def healthz(_request):
    """Liveness probe. No PHI, no auth."""
    return JsonResponse({"status": "ok", "service": "clinara-api"})


urlpatterns = [
    path("healthz", healthz, name="healthz"),
    # path("api/v1/", include("clinara.api_v1")),  # wired up per phase
]
