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
SECURE_REFERRER_POLICY = "same-origin"
X_FRAME_OPTIONS = "DENY"

# The production DB role is a non-superuser so PostgreSQL Row-Level Security is enforced.
# No DJANGO_LOCAL_SUPERUSER_DB escape hatch here — intentionally.

# GA hardening — LLM provider failover (spec §11.4). Preference order the reliability layer
# walks; a provider under a MODEL_PROVIDER (or GLOBAL) kill switch is skipped, and if none is
# available the caller falls back to the deterministic/no-LLM path. Providers must be under an
# executed BAA before being listed here (see docs/compliance).
LLM_PROVIDER_PREFERENCE = ["anthropic", "openai"]

# Phase 7 — Real EMR Connectivity. SMART Backend Services write-back endpoints per vendor,
# populated from the environment (secrets/keys stay in the vault; only non-secret endpoints
# and client ids are set here). A vendor is enabled only when its base_url is present.
import os as _os  # noqa: E402


def _ehr_vendor(prefix: str, vendor: str) -> dict | None:
    base = _os.environ.get(f"{prefix}_BASE_URL")
    if not base:
        return None
    return {
        "vendor": vendor,
        "base_url": base,
        "token_url": _os.environ.get(f"{prefix}_TOKEN_URL", ""),
        "client_id": _os.environ.get(f"{prefix}_CLIENT_ID", ""),
        "scopes": [s for s in _os.environ.get(f"{prefix}_SCOPES", "").split() if s],
    }


EHR_WRITE_BACK = {
    vendor: cfg
    for vendor, cfg in (
        ("epic", _ehr_vendor("EHR_EPIC", "epic")),
        ("athena", _ehr_vendor("EHR_ATHENA", "athena")),
    )
    if cfg is not None
}
