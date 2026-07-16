"""SMART App Launch — *EHR launch* authorization code flow (plan Phase 8 — closes gap G4).

Phase 7 implemented SMART *Backend Services* (system-to-system, no user) for write-back.
This module implements the other half of SMART-on-FHIR: the **EHR launch** sequence, where a
clinician opens Clinara *from inside* their EHR and is signed in without a separate login
(SMART App Launch 2.x, "EHR Launch" + OpenID Connect):

    1. The EHR opens the app's launch URL with ``iss`` (the FHIR base) and an opaque
       ``launch`` token.
    2. The app discovers the authorization + token endpoints from
       ``{iss}/.well-known/smart-configuration``.
    3. The app redirects the browser to the EHR's *authorize* endpoint
       (``response_type=code``, ``aud=iss``, the ``launch`` token, ``openid fhirUser`` scope,
       an anti-forgery ``state`` and an OIDC ``nonce``).
    4. The EHR authenticates the clinician and redirects back with ``code`` + ``state``.
    5. The app exchanges the ``code`` at the token endpoint for an access token, the launch
       context (``patient``/``encounter``), and an OIDC ``id_token``.
    6. The app validates the ``id_token`` (signature, ``iss``, ``aud``, ``exp``, ``nonce``)
       and reads the clinician's identity (``fhirUser``/``sub``) to bridge to a Clinara user.

Like the rest of the SDK, everything here is **pure and injected**: the HTTP call goes
through ``HttpTransport``, the clock is passed in, ``state``/``nonce`` come from injected
factories, and the ``id_token`` signature is checked by an injected ``Verifier``. That keeps
the module crypto/HTTP-free and lets the whole flow be exercised deterministically against a
fake EHR. Production injects an RS256 ``Verifier`` resolved from the EHR's JWKS; dev/test uses
the bundled ``HmacVerifier`` — the *flow* (redirect shaping, state/nonce round-trip, token
exchange, claim validation) is identical either way, and that is the part that must be right.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
from dataclasses import dataclass
from typing import Any, Protocol
from urllib.parse import urlencode

from .smart import b64url
from .transport import HttpRequest, HttpTransport, TransportError

_WELL_KNOWN = "/.well-known/smart-configuration"


class SmartLaunchError(RuntimeError):
    """The EHR launch could not be completed (discovery, state/nonce, token, or claim
    validation failed). Never carries PHI — only the protocol-level reason."""


# ---- id_token signature verification (injected, mirrors smart.Signer) ----

class Verifier(Protocol):
    """Verifies a JWS signing input against a signature. Production: an RS256 verifier over the
    EHR's published JWKS key. Dev/test: ``HmacVerifier``. ``alg`` is matched against the token
    header so a token signed with an unexpected algorithm is rejected (alg-confusion guard)."""

    @property
    def alg(self) -> str: ...

    def verify(self, signing_input: bytes, signature: bytes) -> bool: ...


@dataclass(frozen=True)
class HmacVerifier:
    """HMAC verifier (default HS256) for local/dev/test — stdlib only, no key management.

    Real EHRs sign the ``id_token`` with an asymmetric key (RS256); deployments inject an
    RS256 verifier that resolves the key from the issuer's JWKS. The validation *flow* does not
    depend on which is used, so this is a faithful stand-in for everything but the primitive."""

    secret: bytes
    alg: str = "HS256"

    _DIGESTS = {"HS256": hashlib.sha256, "HS384": hashlib.sha384, "HS512": hashlib.sha512}

    def verify(self, signing_input: bytes, signature: bytes) -> bool:
        digest = self._DIGESTS.get(self.alg)
        if digest is None:
            raise ValueError(f"unsupported HMAC alg {self.alg!r}")
        expected = hmac.new(self.secret, signing_input, digest).digest()
        return hmac.compare_digest(expected, signature)  # constant-time


# ---- configuration + value objects ----

@dataclass(frozen=True)
class LaunchConfig:
    """The app's SMART registration for one EHR connection.

    ``client_id`` and ``redirect_uri`` are what the app was registered with in the EHR's app
    catalog; ``scopes`` always includes ``openid`` + ``fhirUser`` (to receive an id_token that
    identifies the clinician) and ``launch`` (to receive the EHR launch context)."""

    client_id: str
    redirect_uri: str
    scopes: tuple[str, ...] = ("openid", "fhirUser", "launch")

    @property
    def scope_str(self) -> str:
        return " ".join(self.scopes)


@dataclass(frozen=True)
class SmartEndpoints:
    authorize_url: str
    token_url: str


@dataclass(frozen=True)
class LaunchContext:
    """The result of a completed token exchange — the clinician identity + launch context.

    ``fhir_user`` is the FHIR reference to the clinician (e.g. ``Practitioner/123``) used to
    bridge to a Clinara user; ``patient``/``encounter`` scope the review surface to the chart
    the EHR launched against; ``expires_in`` bounds the session lifetime to the EHR's."""

    access_token: str
    id_token_claims: dict[str, Any]
    patient: str | None = None
    encounter: str | None = None
    scope: str = ""
    expires_in: int = 300

    @property
    def subject(self) -> str:
        """The stable clinician identifier: prefer ``fhirUser`` (FHIR reference), else ``sub``."""
        return str(
            self.id_token_claims.get("fhirUser")
            or self.id_token_claims.get("sub")
            or ""
        )


# ---- flow steps (each pure / injected) ----

def discover_endpoints(*, iss: str, transport: HttpTransport) -> SmartEndpoints:
    """Fetch the EHR's SMART configuration (step 2). ``iss`` is the FHIR base URL the EHR sent.

    Reads ``authorization_endpoint`` + ``token_endpoint`` from the well-known document — never
    hard-codes vendor URLs, so the same code points at any conformant Epic/Athena/other server.
    """
    url = iss.rstrip("/") + _WELL_KNOWN
    try:
        resp = transport.request(HttpRequest(method="GET", url=url,
                                             headers={"Accept": "application/json"}))
    except TransportError as exc:
        raise SmartLaunchError(f"smart-configuration unreachable: {exc}") from exc
    if not resp.ok:
        raise SmartLaunchError(f"smart-configuration returned {resp.status}")
    data = resp.json() or {}
    authorize = data.get("authorization_endpoint")
    token = data.get("token_endpoint")
    if not authorize or not token:
        raise SmartLaunchError("smart-configuration missing authorize/token endpoint")
    return SmartEndpoints(authorize_url=str(authorize), token_url=str(token))


def build_authorize_url(
    *,
    config: LaunchConfig,
    endpoints: SmartEndpoints,
    iss: str,
    launch: str,
    state: str,
    nonce: str,
) -> str:
    """Build the browser redirect to the EHR authorize endpoint (step 3).

    ``aud=iss`` binds the request to the launching server (token-audience confusion guard);
    ``state`` is the anti-forgery value echoed back on the callback; ``nonce`` binds the later
    id_token to this request. The ``launch`` token is passed straight through so the EHR knows
    which chart/context to authorize.
    """
    params = {
        "response_type": "code",
        "client_id": config.client_id,
        "redirect_uri": config.redirect_uri,
        "scope": config.scope_str,
        "state": state,
        "aud": iss,
        "launch": launch,
        "nonce": nonce,
    }
    sep = "&" if "?" in endpoints.authorize_url else "?"
    return endpoints.authorize_url + sep + urlencode(params)


def exchange_code(
    *,
    config: LaunchConfig,
    endpoints: SmartEndpoints,
    code: str,
    transport: HttpTransport,
    verifier: Verifier,
    now_epoch: float,
    iss: str,
    expected_nonce: str,
    leeway_seconds: float = 60.0,
) -> LaunchContext:
    """Exchange the authorization ``code`` for tokens and validate the id_token (steps 5-6).

    Raises ``SmartLaunchError`` on any failure — a rejected grant, a missing id_token, or an
    id_token whose signature/``iss``/``aud``/``exp``/``nonce`` does not check out. On success
    returns the clinician identity + launch context the caller bridges to a Clinara session.
    """
    form = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": config.redirect_uri,
        "client_id": config.client_id,
    }
    try:
        resp = transport.request(HttpRequest(
            method="POST",
            url=endpoints.token_url,
            headers={"Content-Type": "application/x-www-form-urlencoded",
                     "Accept": "application/json"},
            body=urlencode(form).encode("ascii"),
        ))
    except TransportError as exc:
        raise SmartLaunchError(f"token endpoint unreachable: {exc}") from exc
    if not resp.ok:
        detail = resp.body.decode("utf-8", "replace")[:200] if resp.body else ""
        raise SmartLaunchError(f"token endpoint returned {resp.status}: {detail}")

    data = resp.json() or {}
    id_token = data.get("id_token")
    if not id_token:
        raise SmartLaunchError("token response missing id_token")
    claims = decode_id_token(
        id_token, verifier=verifier, now_epoch=now_epoch,
        expected_iss=iss, expected_aud=config.client_id,
        expected_nonce=expected_nonce, leeway_seconds=leeway_seconds,
    )
    if not data.get("access_token"):
        raise SmartLaunchError("token response missing access_token")
    return LaunchContext(
        access_token=str(data["access_token"]),
        id_token_claims=claims,
        patient=_str_or_none(data.get("patient")),
        encounter=_str_or_none(data.get("encounter")),
        scope=str(data.get("scope", config.scope_str)),
        expires_in=int(data.get("expires_in", 300)),
    )


def decode_id_token(
    id_token: str,
    *,
    verifier: Verifier,
    now_epoch: float,
    expected_iss: str,
    expected_aud: str,
    expected_nonce: str,
    leeway_seconds: float = 60.0,
) -> dict[str, Any]:
    """Verify + validate an OIDC id_token (step 6). Returns its claims, or raises.

    Checks, in order: three JWS segments; header ``alg`` matches the verifier (alg-confusion
    guard); the signature verifies; ``iss`` matches the launching server; ``aud`` contains our
    ``client_id``; ``exp`` is in the future (± leeway); ``nonce`` matches the value we sent.
    Every failure is a ``SmartLaunchError`` — the token is never trusted on a partial check.
    """
    parts = id_token.split(".")
    if len(parts) != 3:
        raise SmartLaunchError("id_token is not a well-formed JWS")
    header_seg, claims_seg, sig_seg = parts
    try:
        header = json.loads(_b64url_decode(header_seg))
        claims = json.loads(_b64url_decode(claims_seg))
        signature = _b64url_decode(sig_seg)
    except (ValueError, json.JSONDecodeError) as exc:
        raise SmartLaunchError("id_token segments are not decodable") from exc

    if header.get("alg") != verifier.alg:
        raise SmartLaunchError(
            f"id_token alg {header.get('alg')!r} != expected {verifier.alg!r}")
    signing_input = f"{header_seg}.{claims_seg}".encode("ascii")
    if not verifier.verify(signing_input, signature):
        raise SmartLaunchError("id_token signature does not verify")

    if claims.get("iss") != expected_iss:
        raise SmartLaunchError("id_token iss mismatch")
    aud = claims.get("aud")
    aud_ok = expected_aud == aud or (isinstance(aud, list) and expected_aud in aud)
    if not aud_ok:
        raise SmartLaunchError("id_token aud mismatch")
    exp = claims.get("exp")
    if not isinstance(exp, (int, float)) or now_epoch > exp + leeway_seconds:
        raise SmartLaunchError("id_token is expired or missing exp")
    if claims.get("nonce") != expected_nonce:
        raise SmartLaunchError("id_token nonce mismatch (possible replay)")
    return claims


# ---- test/dev helper: build a signed id_token (mirrors HmacVerifier) ----

def build_test_id_token(
    *,
    secret: bytes,
    iss: str,
    aud: str,
    sub: str,
    nonce: str,
    exp_epoch: float,
    fhir_user: str | None = None,
    alg: str = "HS256",
    extra_claims: dict[str, Any] | None = None,
) -> str:
    """Produce an HS-signed id_token for tests/dev that ``HmacVerifier`` accepts.

    Production id_tokens come from the EHR (RS256); this only exists so the launch flow can be
    exercised end-to-end against a fake token endpoint without real EHR keys.
    """
    _digests = {"HS256": hashlib.sha256, "HS384": hashlib.sha384, "HS512": hashlib.sha512}
    header = {"alg": alg, "typ": "JWT"}
    claims: dict[str, Any] = {"iss": iss, "aud": aud, "sub": sub, "nonce": nonce,
                              "exp": int(exp_epoch)}
    if fhir_user:
        claims["fhirUser"] = fhir_user
    if extra_claims:
        claims.update(extra_claims)
    seg = [
        b64url(json.dumps(header, separators=(",", ":"), sort_keys=True).encode()),
        b64url(json.dumps(claims, separators=(",", ":"), sort_keys=True).encode()),
    ]
    signing_input = ".".join(seg).encode("ascii")
    signature = hmac.new(secret, signing_input, _digests[alg]).digest()
    return ".".join(seg) + "." + b64url(signature)


# ---- internals ----

def _b64url_decode(segment: str) -> bytes:
    padding = "=" * (-len(segment) % 4)
    return base64.urlsafe_b64decode(segment + padding)


def _str_or_none(value: Any) -> str | None:
    return str(value) if value not in (None, "") else None


__all__ = [
    "SmartLaunchError",
    "Verifier",
    "HmacVerifier",
    "LaunchConfig",
    "SmartEndpoints",
    "LaunchContext",
    "discover_endpoints",
    "build_authorize_url",
    "exchange_code",
    "decode_id_token",
    "build_test_id_token",
]
