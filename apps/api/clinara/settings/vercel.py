"""Settings for the hosted Vercel serverless deployment.

Serves the Django web + REST API + clinician console against a Neon PostgreSQL database.
This surface is the request/response half of Clinara. The background half — Celery workers,
the outbox relay, and the daily retention/purge beat — does NOT run on Vercel's serverless
runtime; those paths run in the full container stack (docker-compose / infrastructure). The
synchronous service layer the console drives (ingest → classify → review → analytics) runs
fully here.

Key differences from ``production.py`` (which targets a container behind a vault):
- database comes from ``DATABASE_URL`` (Neon), with SSL required and short-lived connections
  suited to serverless + a connection pooler;
- no Redis: the cache is in-process and sessions live in the database, so a warm/cold
  serverless invocation always finds the session in Neon;
- the clinician console is enabled (``ENABLE_CONSOLE``) so the deployed URL is usable;
- host/CSRF trust is derived from the Vercel-provided deployment domains.
"""
from __future__ import annotations

import os

from .base import *  # noqa: F401,F403
from .base import env

DEBUG = env.bool("DJANGO_DEBUG", default=False)

# ---- Allowed hosts / CSRF trust (Vercel injects the deployment domains) ----
ALLOWED_HOSTS = env.list("DJANGO_ALLOWED_HOSTS", default=[])
for _var in ("VERCEL_URL", "VERCEL_BRANCH_URL", "VERCEL_PROJECT_PRODUCTION_URL"):
    _host = os.environ.get(_var)
    if _host:
        ALLOWED_HOSTS.append(_host)
# Every Vercel deployment alias lives under *.vercel.app; trust the suffix so preview and
# production aliases both resolve without re-deploying to update an env var.
ALLOWED_HOSTS.append(".vercel.app")

CSRF_TRUSTED_ORIGINS = [
    f"https://{h.lstrip('.')}" for h in ALLOWED_HOSTS if h and h != ".vercel.app"
]
CSRF_TRUSTED_ORIGINS.append("https://*.vercel.app")

# ---- Database: Neon PostgreSQL ----
# The Neon Marketplace integration injects a pooled DATABASE_URL (PgBouncer, transaction mode)
# and an unpooled/direct URL. Tenant isolation here is enforced with a *session-level* GUC —
# TenantContextMiddleware runs ``set_config('app.current_tenant', …, is_local=false)`` once per
# request and every tenant-scoped table has a FORCE ROW LEVEL SECURITY policy keyed on it
# (core.rls). A transaction-mode pooler does not keep session state across the request's
# statements, which would silently break that GUC — so we connect on the DIRECT endpoint where
# the session variable persists for the whole request. Light demo traffic + CONN_MAX_AGE below
# keeps direct-connection usage well within Neon's limits.
import environ as _environ  # noqa: E402

_db_url = (
    os.environ.get("DATABASE_URL_UNPOOLED")
    or os.environ.get("POSTGRES_URL_NON_POOLING")
    or os.environ["DATABASE_URL"]
)
DATABASES = {"default": _environ.Env.db_url_config(_db_url)}
DATABASES["default"]["ENGINE"] = "django.db.backends.postgresql"
DATABASES["default"]["CONN_MAX_AGE"] = env.int("DB_CONN_MAX_AGE", default=0)
DATABASES["default"].setdefault("OPTIONS", {})
# Neon requires TLS; the pooled endpoint terminates it.
DATABASES["default"]["OPTIONS"].setdefault("sslmode", "require")

# ---- No Redis on serverless: in-process cache, database-backed sessions ----
CACHES = {
    "default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}
}
SESSION_ENGINE = "django.contrib.sessions.backends.db"

# ---- Clinician console + root redirect ----
ENABLE_CONSOLE = True

# ---- Security hardening (Vercel terminates TLS at the edge) ----
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
# The Vercel edge already serves HTTPS; an app-level redirect risks a loop, so it is opt-in.
SECURE_SSL_REDIRECT = env.bool("DJANGO_SSL_REDIRECT", default=False)
SECURE_HSTS_SECONDS = env.int("DJANGO_HSTS_SECONDS", default=0)
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
# The console is same-origin (not framed); the embedded SMART surface is framed by the EHR
# but is not part of the Vercel demo. DENY keeps the console from being framed.
X_FRAME_OPTIONS = "DENY"

# ---- Static files ----
# The console + embedded templates are self-contained (inline CSS/JS), so there are no static
# assets to serve for the demo surface. WhiteNoise handles any Django-contrib static safely on
# the read-only serverless filesystem without a separate CDN.
STATIC_ROOT = os.path.join("/tmp", "staticfiles")
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedStaticFilesStorage",
    },
}
_wn = "whitenoise.middleware.WhiteNoiseMiddleware"
if _wn not in MIDDLEWARE:  # noqa: F405
    # Insert directly after SecurityMiddleware, per WhiteNoise guidance.
    MIDDLEWARE.insert(1, _wn)  # noqa: F405
