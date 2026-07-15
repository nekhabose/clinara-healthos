"""Production settings. Secrets come from AWS Secrets Manager via the environment."""
from .base import *  # noqa: F401,F403

DEBUG = False

# Security hardening (spec §10.3).
SECURE_SSL_REDIRECT = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_HSTS_SECONDS = 31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = "DENY"

# The production DB role is a non-superuser so PostgreSQL Row-Level Security is enforced.
# No DJANGO_LOCAL_SUPERUSER_DB escape hatch here — intentionally.
