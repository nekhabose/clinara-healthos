"""Phase 8 — SMART App Launch (EHR launch) flow, exercised against a vendor-emulating fake.

Proves the pure launch stack: config discovery, authorize-URL shaping (state/nonce/aud/launch),
code→token exchange, and — the security-critical part — id_token validation: signature, iss,
aud, exp, and nonce are each independently enforced, so a tampered or replayed token is rejected.
Production swaps the HMAC verifier for RS256-over-JWKS by injection; the flow is identical.
"""
import json

import pytest
from clinara_integration_sdk import (
    HttpResponse,
    LaunchConfig,
    SmartEndpoints,
    SmartLaunchError,
    build_authorize_url,
    build_test_id_token,
    decode_id_token,
    discover_endpoints,
    exchange_code,
)
from clinara_integration_sdk.smart_launch import HmacVerifier

ISS = "https://fhir.ehr.example/r4"
AUTHORIZE = "https://auth.ehr.example/authorize"
TOKEN = "https://auth.ehr.example/token"
CLIENT_ID = "clinara-embedded"
REDIRECT = "https://clinara.example/api/v1/smart/callback"
SECRET = b"dev-id-token-signing-secret"
NOW = 1_700_000_000.0


def _config() -> LaunchConfig:
    return LaunchConfig(client_id=CLIENT_ID, redirect_uri=REDIRECT)


def _endpoints() -> SmartEndpoints:
    return SmartEndpoints(authorize_url=AUTHORIZE, token_url=TOKEN)


class FakeEhr:
    """Emulates the well-known discovery doc and the token endpoint of a SMART EHR."""

    def __init__(self, *, id_token: str | None = "__default__", extra_token: dict | None = None):
        self._id_token = id_token
        self._extra = extra_token or {}

    def request(self, req):
        if req.url.endswith("/.well-known/smart-configuration"):
            return HttpResponse(200, {}, json.dumps({
                "authorization_endpoint": AUTHORIZE, "token_endpoint": TOKEN,
            }).encode())
        if req.url == TOKEN:
            body: dict = {"access_token": "at-1", "token_type": "Bearer", "expires_in": 900,
                          "patient": "Patient/abc", "encounter": "Encounter/xyz",
                          "scope": "openid fhirUser launch"}
            if self._id_token == "__default__":
                body["id_token"] = build_test_id_token(
                    secret=SECRET, iss=ISS, aud=CLIENT_ID, sub="user-1",
                    nonce="nonce-1", exp_epoch=NOW + 3600, fhir_user="Practitioner/dr-1")
            elif self._id_token is not None:
                body["id_token"] = self._id_token
            body.update(self._extra)
            return HttpResponse(200, {}, json.dumps(body).encode())
        raise AssertionError(f"unexpected request {req.url}")


# ---- discovery ----

def test_discover_endpoints_reads_well_known():
    ep = discover_endpoints(iss=ISS, transport=FakeEhr())
    assert ep.authorize_url == AUTHORIZE and ep.token_url == TOKEN


def test_discovery_missing_endpoints_raises():
    class Empty:
        def request(self, req):
            return HttpResponse(200, {}, b"{}")
    with pytest.raises(SmartLaunchError):
        discover_endpoints(iss=ISS, transport=Empty())


# ---- authorize redirect ----

def test_build_authorize_url_carries_state_nonce_aud_and_launch():
    url = build_authorize_url(config=_config(), endpoints=_endpoints(), iss=ISS,
                              launch="opaque-launch", state="st-1", nonce="nonce-1")
    assert url.startswith(AUTHORIZE + "?")
    assert "response_type=code" in url
    assert "state=st-1" in url and "nonce=nonce-1" in url
    assert "launch=opaque-launch" in url
    assert f"aud={ISS.replace(':', '%3A').replace('/', '%2F')}" in url
    assert "scope=openid+fhirUser+launch" in url


# ---- happy-path exchange ----

def test_exchange_code_returns_identity_and_launch_context():
    ctx = exchange_code(config=_config(), endpoints=_endpoints(), code="auth-code",
                        transport=FakeEhr(), verifier=HmacVerifier(SECRET), now_epoch=NOW,
                        iss=ISS, expected_nonce="nonce-1")
    assert ctx.subject == "Practitioner/dr-1"  # prefers fhirUser
    assert ctx.patient == "Patient/abc" and ctx.encounter == "Encounter/xyz"
    assert ctx.expires_in == 900
    assert ctx.access_token == "at-1"


def test_subject_falls_back_to_sub_without_fhir_user():
    token = build_test_id_token(secret=SECRET, iss=ISS, aud=CLIENT_ID, sub="user-99",
                                nonce="nonce-1", exp_epoch=NOW + 3600)
    ctx = exchange_code(config=_config(), endpoints=_endpoints(), code="c",
                        transport=FakeEhr(id_token=token), verifier=HmacVerifier(SECRET),
                        now_epoch=NOW, iss=ISS, expected_nonce="nonce-1")
    assert ctx.subject == "user-99"


# ---- token endpoint / response failures ----

def test_token_error_status_raises():
    class Rejects:
        def request(self, req):
            return HttpResponse(400, {}, b'{"error":"invalid_grant"}')
    with pytest.raises(SmartLaunchError):
        exchange_code(config=_config(), endpoints=_endpoints(), code="c", transport=Rejects(),
                      verifier=HmacVerifier(SECRET), now_epoch=NOW, iss=ISS,
                      expected_nonce="nonce-1")


def test_missing_id_token_raises():
    with pytest.raises(SmartLaunchError, match="missing id_token"):
        exchange_code(config=_config(), endpoints=_endpoints(), code="c",
                      transport=FakeEhr(id_token=None), verifier=HmacVerifier(SECRET),
                      now_epoch=NOW, iss=ISS, expected_nonce="nonce-1")


# ---- id_token validation: each check is independently enforced ----

def _token(**overrides):
    base = dict(secret=SECRET, iss=ISS, aud=CLIENT_ID, sub="u", nonce="nonce-1",
                exp_epoch=NOW + 3600, fhir_user="Practitioner/dr-1")
    base.update(overrides)
    return build_test_id_token(**base)


def test_valid_id_token_decodes():
    claims = decode_id_token(_token(), verifier=HmacVerifier(SECRET), now_epoch=NOW,
                             expected_iss=ISS, expected_aud=CLIENT_ID, expected_nonce="nonce-1")
    assert claims["fhirUser"] == "Practitioner/dr-1"


def test_tampered_signature_rejected():
    tok = _token()
    body = tok.rsplit(".", 1)[0] + ".AAAA"  # replace signature
    with pytest.raises(SmartLaunchError, match="signature"):
        decode_id_token(body, verifier=HmacVerifier(SECRET), now_epoch=NOW,
                        expected_iss=ISS, expected_aud=CLIENT_ID, expected_nonce="nonce-1")


def test_wrong_secret_rejected():
    with pytest.raises(SmartLaunchError, match="signature"):
        decode_id_token(_token(), verifier=HmacVerifier(b"other-secret"), now_epoch=NOW,
                        expected_iss=ISS, expected_aud=CLIENT_ID, expected_nonce="nonce-1")


def test_iss_mismatch_rejected():
    with pytest.raises(SmartLaunchError, match="iss"):
        decode_id_token(_token(iss="https://evil.example"), verifier=HmacVerifier(SECRET),
                        now_epoch=NOW, expected_iss=ISS, expected_aud=CLIENT_ID,
                        expected_nonce="nonce-1")


def test_aud_mismatch_rejected():
    with pytest.raises(SmartLaunchError, match="aud"):
        decode_id_token(_token(aud="someone-else"), verifier=HmacVerifier(SECRET),
                        now_epoch=NOW, expected_iss=ISS, expected_aud=CLIENT_ID,
                        expected_nonce="nonce-1")


def test_expired_token_rejected():
    with pytest.raises(SmartLaunchError, match="expired"):
        decode_id_token(_token(exp_epoch=NOW - 3600), verifier=HmacVerifier(SECRET),
                        now_epoch=NOW, expected_iss=ISS, expected_aud=CLIENT_ID,
                        expected_nonce="nonce-1")


def test_nonce_mismatch_rejected_as_replay():
    with pytest.raises(SmartLaunchError, match="nonce"):
        decode_id_token(_token(nonce="stale-nonce"), verifier=HmacVerifier(SECRET),
                        now_epoch=NOW, expected_iss=ISS, expected_aud=CLIENT_ID,
                        expected_nonce="nonce-1")


def test_alg_confusion_rejected():
    """A token advertising an alg the verifier does not expect is rejected before verify()."""
    tok = build_test_id_token(secret=SECRET, iss=ISS, aud=CLIENT_ID, sub="u",
                              nonce="nonce-1", exp_epoch=NOW + 3600, alg="HS512")
    with pytest.raises(SmartLaunchError, match="alg"):
        decode_id_token(tok, verifier=HmacVerifier(SECRET, alg="HS256"), now_epoch=NOW,
                        expected_iss=ISS, expected_aud=CLIENT_ID, expected_nonce="nonce-1")
