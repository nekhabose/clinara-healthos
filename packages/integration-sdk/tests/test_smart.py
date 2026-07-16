"""SMART Backend Services auth (plan Phase 7 — closes G2).

Validates the assertion shape (RFC 7523), the client_credentials grant request, token
caching/refresh, scope passthrough, and error classification — against a fake token endpoint,
so the flow is proven without a live EMR or any crypto/HTTP dependency.
"""
import base64
import hmac
import json
from hashlib import sha384

import pytest
from clinara_integration_sdk import (
    HmacSigner,
    HttpRequest,
    HttpResponse,
    SmartAuthError,
    SmartBackendAuth,
    SmartConfig,
    build_client_assertion,
)
from clinara_integration_sdk.transport import TransportError

SECRET = b"unit-test-signing-secret"
TOKEN_URL = "https://ehr.example/oauth2/token"


def _b64url_decode(seg: str) -> bytes:
    return base64.urlsafe_b64decode(seg + "=" * (-len(seg) % 4))


class FakeTokenServer:
    """Emulates an EHR token endpoint. Records requests; returns configurable responses."""

    def __init__(self, *, expires_in=300, status=200, scope="system/*.read"):
        self.expires_in = expires_in
        self.status = status
        self.scope = scope
        self.requests: list[HttpRequest] = []
        self.token_seq = 0

    def request(self, req: HttpRequest) -> HttpResponse:
        self.requests.append(req)
        if self.status != 200:
            return HttpResponse(self.status, {}, b'{"error":"invalid_client"}')
        self.token_seq += 1
        body = {
            "access_token": f"tok-{self.token_seq}",
            "token_type": "Bearer",
            "expires_in": self.expires_in,
            "scope": self.scope,
        }
        return HttpResponse(200, {"Content-Type": "application/json"},
                            json.dumps(body).encode())


def _auth(server, *, scopes=("system/*.read",), expires_in=None, jti="jti-1"):
    if expires_in is not None:
        server.expires_in = expires_in
    cfg = SmartConfig(client_id="clinara-client", token_url=TOKEN_URL, scopes=scopes)
    counter = {"n": 0}

    def jti_factory():
        counter["n"] += 1
        return f"{jti}-{counter['n']}"

    return SmartBackendAuth(cfg, HmacSigner(SECRET), server, jti_factory=jti_factory)


def test_client_assertion_has_smart_backend_claims_and_valid_signature():
    assertion = build_client_assertion(
        client_id="clinara-client", token_url=TOKEN_URL,
        signer=HmacSigner(SECRET), now_epoch=1_000_000.0, jti="unique-jti", ttl_seconds=300,
    )
    header_seg, claims_seg, sig_seg = assertion.split(".")
    header = json.loads(_b64url_decode(header_seg))
    claims = json.loads(_b64url_decode(claims_seg))

    assert header["alg"] == "HS384" and header["typ"] == "JWT"
    # SMART Backend Services: iss == sub == client_id, aud == token endpoint.
    assert claims["iss"] == claims["sub"] == "clinara-client"
    assert claims["aud"] == TOKEN_URL
    assert claims["jti"] == "unique-jti"
    assert claims["exp"] - claims["iat"] == 300

    expected = hmac.new(SECRET, f"{header_seg}.{claims_seg}".encode(), sha384).digest()
    assert _b64url_decode(sig_seg) == expected


def test_token_fetch_sends_client_credentials_grant_with_assertion():
    server = FakeTokenServer()
    auth = _auth(server)
    token = auth.token(now_epoch=1000.0)

    assert token.value == "tok-1"
    body = server.requests[0].body.decode()
    assert "grant_type=client_credentials" in body
    assert "client_assertion_type=urn" in body
    assert "client_assertion=" in body
    assert "scope=" in body  # requested scopes forwarded


def test_token_is_cached_until_near_expiry():
    server = FakeTokenServer(expires_in=300)
    auth = _auth(server)
    t1 = auth.token(now_epoch=1000.0)
    t2 = auth.token(now_epoch=1000.0 + 100)  # well within the 300s lifetime
    assert t1.value == t2.value == "tok-1"
    assert auth.token_requests == 1  # exactly one network round-trip


def test_token_refreshes_after_expiry_window():
    server = FakeTokenServer(expires_in=300)
    auth = _auth(server)
    auth.token(now_epoch=1000.0)
    # 1000 + 300 - 60 skew = 1240 is the refresh boundary; go past it.
    refreshed = auth.token(now_epoch=1000.0 + 250)
    assert refreshed.value == "tok-2"
    assert auth.token_requests == 2


def test_scope_passed_through_from_response():
    server = FakeTokenServer(scope="system/Observation.read system/Task.write")
    auth = _auth(server)
    token = auth.token(now_epoch=1000.0)
    assert "Task.write" in token.scope


def test_error_status_raises_smart_auth_error():
    server = FakeTokenServer(status=401)
    auth = _auth(server)
    with pytest.raises(SmartAuthError):
        auth.token(now_epoch=1000.0)


def test_missing_access_token_raises():
    class Empty:
        def request(self, req):
            return HttpResponse(200, {}, b"{}")

    auth = _auth(Empty())
    with pytest.raises(SmartAuthError):
        auth.token(now_epoch=1000.0)


def test_transport_error_propagates():
    class Broken:
        def request(self, req):
            raise TransportError("connection refused")

    auth = _auth(Broken())
    with pytest.raises(TransportError):
        auth.token(now_epoch=1000.0)


def test_bearer_header_uses_current_token():
    server = FakeTokenServer()
    auth = _auth(server)
    header = auth.bearer_header(now_epoch=1000.0)
    assert header["Authorization"] == "Bearer tok-1"
