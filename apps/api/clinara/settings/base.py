"""Base Django settings shared across environments.

Environment-specific overrides live in local.py / production.py.
"""
from __future__ import annotations

from pathlib import Path

import environ

BASE_DIR = Path(__file__).resolve().parent.parent.parent

env = environ.Env()

SECRET_KEY = env("DJANGO_SECRET_KEY", default="dev-insecure-change-me")
DEBUG = env.bool("DJANGO_DEBUG", default=False)
ALLOWED_HOSTS = env.list("DJANGO_ALLOWED_HOSTS", default=["localhost", "127.0.0.1"])

# ---- Applications ----
DJANGO_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
]

THIRD_PARTY_APPS = [
    "rest_framework",
]

# Platform infrastructure app (base models, outbox, RLS).
PLATFORM_APPS = [
    "core",
]

# Modular-monolith domain modules (spec §7.4). Phase 0 activates a subset;
# the rest are boundary stubs so the structure is stable from day one.
DOMAIN_APPS = [
    "domains.identity",
    "domains.tenants",
    "domains.audit",
    "domains.operations",
    # Phase 1 — Results Intelligence MVP:
    "domains.integrations",
    "domains.terminology",
    "domains.clinical_data",
    "domains.context",
    "domains.workflows",
    "domains.generation",
    "domains.safety",
    # Phase 2 — Clinical Rule Studio:
    "domains.protocols",
    # Phase 3+ (declared here as the code lands):
    # "domains.delivery",
    # "domains.feedback",
    # "domains.analytics",
]

INSTALLED_APPS = DJANGO_APPS + THIRD_PARTY_APPS + PLATFORM_APPS + DOMAIN_APPS

AUTH_USER_MODEL = "identity.User"

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    # Clinara cross-cutting middleware:
    "clinara.middleware.tenant.TenantContextMiddleware",       # sets RLS session var per request
    "clinara.middleware.phi_safe_logging.CorrelationIdMiddleware",
]

ROOT_URLCONF = "clinara.urls"
WSGI_APPLICATION = "clinara.wsgi.application"
ASGI_APPLICATION = "clinara.asgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {"context_processors": [
            "django.contrib.auth.context_processors.auth",
            "django.contrib.messages.context_processors.messages",
        ]},
    },
]

# ---- Database (RLS-enforced; app connects as a non-superuser role) ----
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": env("POSTGRES_DB", default="clinara"),
        "USER": env("POSTGRES_USER", default="clinara_app"),
        "PASSWORD": env("POSTGRES_PASSWORD", default="clinara_app"),
        "HOST": env("POSTGRES_HOST", default="localhost"),
        "PORT": env("POSTGRES_PORT", default="5432"),
    }
}

# ---- Cache / Celery ----
REDIS_URL = env("REDIS_URL", default="redis://localhost:6379/0")
CACHES = {
    "default": {"BACKEND": "django.core.cache.backends.redis.RedisCache", "LOCATION": REDIS_URL}
}
CELERY_BROKER_URL = env("CELERY_BROKER_URL", default="redis://localhost:6379/1")
CELERY_RESULT_BACKEND = env("CELERY_RESULT_BACKEND", default="redis://localhost:6379/2")

# ---- DRF ----
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": ["rest_framework.authentication.SessionAuthentication"],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
}

# ---- Clinical content (versioned rule + template artifacts, plan Phase 1) ----
# Rules are data, not code: the engine loads YAML from the repo. Overridable per env.
_REPO_ROOT = BASE_DIR.parent.parent
CLINICAL_RULES_DIR = env("CLINARA_RULES_DIR", default=str(_REPO_ROOT / "clinical" / "protocols"))
CLINICAL_TEMPLATES_PATH = env(
    "CLINARA_TEMPLATES_PATH", default=str(_REPO_ROOT / "clinical" / "templates" / "results.yaml")
)

# ---- i18n / static ----
LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True
STATIC_URL = "static/"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# ---- Logging: structured + PHI-safe (see clinara.middleware.phi_safe_logging) ----
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "filters": {
        "phi_scrub": {"()": "clinara.middleware.phi_safe_logging.PhiScrubFilter"},
        "correlation": {"()": "clinara.middleware.phi_safe_logging.CorrelationIdFilter"},
    },
    "formatters": {
        "json": {"()": "clinara.middleware.phi_safe_logging.JsonFormatter"},
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "json",
            "filters": ["phi_scrub", "correlation"],
        }
    },
    "root": {"handlers": ["console"], "level": "INFO"},
}
