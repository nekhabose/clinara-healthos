"""SMART Backend Services authorization (plan Phase 7 — closes gap G2).

Implements the SMART-on-FHIR *Backend Services* OAuth 2.0 flow used by Epic and Athena for
system-to-system access (HL7 SMART App Launch — "Backend Services"; RFC 7523 JWT client
assertion + RFC 6749 ``client_credentials`` grant):

    1. Build a signed JWT *client assertion* (iss = sub = client_id, aud = token URL, short
       expiry, unique jti).
    2. POST it to the authorization server's token endpoint with
       ``grant_type=client_credentials`` and the requested scopes.
    3. Cache the returned bearer token and reuse it until it is near expiry, then refresh.

Everything here is **pure and injected** — the HTTP call goes through ``HttpTransport``, the
clock is passed in, and the JWT signature is produced by an injected ``Signer``. That keeps
the module free of any crypto/HTTP dependency and lets it be exercised deterministically
against a fake token endpoint. Production injects an RS384 ``Signer`` (asymmetric keys, as
Epic/Athena require); dev/test uses the bundled ``HmacSigner``. The *flow* — assertion
shape, grant request, caching, refresh, scope handling, error classification — is identical
either way, which is the part that has to be correct.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
from dataclasses import dataclass
from typing import Callable, Protocol
from urllib.parse import urlencode

from .transport import HttpRequest, HttpTransport


class SmartAuthError(RuntimeError):
    """The authorization server rejected the token request (bad grant, invalid client, …)."""


def b64url(data: bytes) -> str:
    """Base64url without padding (JWT/JWS encoding, RFC 7515 §2)."""
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


class Signer(Protocol):
    """Signs the JWS signing input. Production: RS384 over an asymmetric key. Dev/test:
    ``HmacSigner``. ``alg`` is emitted verbatim into the JWT header."""

    @property
    def alg(self) -> str: ...

    @property
    def kid(self) -> str | None: ...

    def sign(self, signing_input: bytes) -> bytes: ...


@dataclass(frozen=True)
class HmacSigner:
    """HMAC signer (default HS384) for local/dev/test — stdlib only, no key management.

    Real EMRs require asymmetric signatures; deployments inject an RS384 signer instead. The
    assertion/flow logic does not depend on which is used, so this is a faithful stand-in for
    everything except the cryptographic primitive."""

    secret: bytes
    alg: str = "HS384"
    kid: str | None = None

    _DIGESTS = {"HS256": hashlib.sha256, "HS384": hashlib.sha384, "HS512": hashlib.sha512}

    def sign(self, signing_input: bytes) -> bytes:
        digest = self._DIGESTS.get(self.alg)
        if digest is None:
            raise ValueError(f"unsupported HMAC alg {self.alg!r}")
        return hmac.new(self.secret, signing_input, digest).digest()


def build_client_assertion(
    *,
    client_id: str,
    token_url: str,
    signer: Signer,
    now_epoch: float,
    jti: str,
    ttl_seconds: int = 300,
) -> str:
    """Build a signed JWT client assertion (RFC 7523 §2.2, SMART Backend Services).

    ``iss`` and ``sub`` are both the client id; ``aud`` is the token endpoint; ``exp`` is a
    short window; ``jti`` is unique per request (replay protection). The signer decides the
    algorithm — the header advertises it so the server verifies with the matching key.
    """
    header: dict[str, str] = {"alg": signer.alg, "typ": "JWT"}
    if signer.kid:
        header["kid"] = signer.kid
    issued = int(now_epoch)
    claims = {
        "iss": client_id,
        "sub": client_id,
        "aud": token_url,
        "jti": jti,
        "iat": issued,
        "exp": issued + int(ttl_seconds),
    }
    segments = [
        b64url(json.dumps(header, separators=(",", ":"), sort_keys=True).encode()),
        b64url(json.dumps(claims, separators=(",", ":"), sort_keys=True).encode()),
    ]
    signing_input = ".".join(segments).encode("ascii")
    signature = signer.sign(signing_input)
    return ".".join(segments) + "." + b64url(signature)


@dataclass(frozen=True)
class AccessToken:
    value: str
    expires_at_epoch: float
    scope: str = ""

    def is_fresh(self, now_epoch: float, skew_seconds: float = 60.0) -> bool:
        """Fresh if it will still be valid ``skew_seconds`` from now (refresh before expiry)."""
        return now_epoch < (self.expires_at_epoch - skew_seconds)


@dataclass(frozen=True)
class SmartConfig:
    client_id: str
    token_url: str
    scopes: tuple[str, ...] = ()
    assertion_ttl_seconds: int = 300
    refresh_skew_seconds: float = 60.0

    @property
    def scope_str(self) -> str:
        return " ".join(self.scopes)


_ASSERTION_TYPE = "urn:ietf:params:oauth:client-assertion-type:jwt-bearer"


class SmartBackendAuth:
    """Obtains and caches a SMART Backend Services bearer token, refreshing before expiry.

    Stateful only in its single cached token. ``token(now_epoch)`` returns the cached token
    while fresh and otherwise fetches a new one through the injected transport — so N calls
    within a token's lifetime make exactly one network round-trip.
    """

    def __init__(
        self,
        config: SmartConfig,
        signer: Signer,
        transport: HttpTransport,
        *,
        jti_factory: Callable[[], str],
    ) -> None:
        self._config = config
        self._signer = signer
        self._transport = transport
        self._jti_factory = jti_factory
        self._cached: AccessToken | None = None
        self.token_requests = 0  # observability/testing: count of real token round-trips

    @property
    def cached(self) -> AccessToken | None:
        return self._cached

    def token(self, now_epoch: float) -> AccessToken:
        if self._cached is not None and self._cached.is_fresh(
            now_epoch, self._config.refresh_skew_seconds
        ):
            return self._cached
        self._cached = self._fetch(now_epoch)
        return self._cached

    def bearer_header(self, now_epoch: float) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token(now_epoch).value}"}

    def _fetch(self, now_epoch: float) -> AccessToken:
        assertion = build_client_assertion(
            client_id=self._config.client_id,
            token_url=self._config.token_url,
            signer=self._signer,
            now_epoch=now_epoch,
            jti=self._jti_factory(),
            ttl_seconds=self._config.assertion_ttl_seconds,
        )
        form = {
            "grant_type": "client_credentials",
            "client_assertion_type": _ASSERTION_TYPE,
            "client_assertion": assertion,
        }
        if self._config.scopes:
            form["scope"] = self._config.scope_str
        self.token_requests += 1
        resp = self._transport.request(
            HttpRequest(
                method="POST",
                url=self._config.token_url,
                headers={
                    "Content-Type": "application/x-www-form-urlencoded",
                    "Accept": "application/json",
                },
                body=urlencode(form).encode("ascii"),
            )
        )
        if not resp.ok:
            detail = resp.body.decode("utf-8", "replace")[:300] if resp.body else ""
            raise SmartAuthError(f"token endpoint returned {resp.status}: {detail}")
        data = resp.json() or {}
        access = data.get("access_token")
        if not access:
            raise SmartAuthError("token response missing access_token")
        expires_in = float(data.get("expires_in", 300))
        return AccessToken(
            value=access,
            expires_at_epoch=now_epoch + expires_in,
            scope=data.get("scope", self._config.scope_str),
        )


__all__ = [
    "SmartBackendAuth",
    "SmartConfig",
    "AccessToken",
    "Signer",
    "HmacSigner",
    "SmartAuthError",
    "build_client_assertion",
    "b64url",
]
