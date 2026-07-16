"""Injection seams for the EHR-embedded launch (plan Phase 8).

The launch flow needs an HTTP transport (for discovery + token exchange) and a JWT
``Verifier`` (for the OIDC id_token). Both are built here so the API views stay thin and tests
can swap in fakes by monkeypatching these factories — the same seam pattern Phase 7 uses for
the write-back client. Defaults are production-safe: a stdlib ``UrllibTransport`` and a
verifier resolved from ``settings.EHR_LAUNCH`` (production injects an RS256/JWKS verifier; a
dev HMAC verifier is used only when a dev secret is configured).
"""
from __future__ import annotations

from clinara_integration_sdk import HmacVerifier, HttpTransport, UrllibTransport, Verifier


def launch_transport() -> HttpTransport:
    """The HTTP transport for discovery + token exchange (stdlib-only in production)."""
    return UrllibTransport()


def launch_verifier() -> Verifier:
    """Build the id_token verifier from settings.

    Production sets ``EHR_LAUNCH["id_token_verifier"]`` to an injected RS256/JWKS verifier.
    Dev/demo may set ``EHR_LAUNCH["dev_id_token_secret"]`` to use an HMAC verifier instead.
    Absent both, a launch cannot be completed — fail-closed, never trust an unverifiable token.
    """
    from django.conf import settings

    cfg = getattr(settings, "EHR_LAUNCH", {}) or {}
    injected = cfg.get("id_token_verifier")
    if injected is not None:
        return injected
    secret = cfg.get("dev_id_token_secret")
    if secret:
        return dev_verifier(secret)
    raise RuntimeError("no id_token verifier configured (set EHR_LAUNCH id_token_verifier)")


def dev_verifier(secret: str = "clinara-dev-id-token-key", alg: str = "HS256") -> HmacVerifier:
    """A local/dev HMAC id_token verifier. NEVER for production — real EHRs sign with RS256."""
    return HmacVerifier(secret.encode(), alg=alg)


__all__ = ["launch_transport", "launch_verifier", "dev_verifier"]
