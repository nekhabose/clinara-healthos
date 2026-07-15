"""Phase 8 — EHR-Embedded Clinician Surface (G4 + G5), end-to-end against a fake EHR.

Proves the exit gates:
  * an EHR SMART launch bridges the EHR identity → the correct Clinara user/tenant/role, and
    the launch is audited (G4);
  * the bridge is fail-closed (no identity link ⇒ refused) and tenant-isolated;
  * there is no separate login — the callback establishes the session — and it expires with
    the EHR session (``expires_at`` stamped from the token lifetime);
  * the chart-context panel surfaces the exact labs/patient-context/provenance the decision
    used, so there is no chart digging (G5);
  * the Epic Showroom + Athena Marketplace manifests are valid.

The SMART protocol runs against a vendor-emulating fake transport + an HMAC id_token verifier
(production injects RS256/JWKS); the flow is identical either way.
"""
import json
import uuid
from urllib.parse import parse_qs, urlparse

import pytest
from clinara_integration_sdk import HttpResponse, build_test_id_token
from clinara_integration_sdk.smart_launch import HmacVerifier
from rest_framework.test import APIClient

from domains.context.core import build_context_panel
from domains.context.models import ContextSnapshotRecord
from domains.embedded import services as embedded
from domains.embedded.models import EhrLaunchSession, LaunchStatus
from domains.identity.models import User

pytestmark = pytest.mark.django_db

ISS = "https://fhir.ehr.example/r4"
AUTHORIZE = "https://auth.ehr.example/authorize"
TOKEN = "https://auth.ehr.example/token"
CLIENT_ID = "clinara-embedded"
REDIRECT = "https://app.clinara.health/api/v1/smart/callback"
SECRET = b"dev-id-token-signing-secret"
SUBJECT = "Practitioner/dr-1"


class FakeEhr:
    """Emulates an EHR's SMART discovery doc + token endpoint. The token endpoint returns
    whatever id_token the test stages (mimicking the EHR echoing back the request nonce)."""

    def __init__(self):
        self.id_token: str | None = None
        self.patient = "Patient/abc"
        self.encounter = "Encounter/xyz"
        self.expires_in = 900

    def stage_id_token(self, *, nonce: str, sub: str = "u", fhir_user: str | None = SUBJECT):
        self.id_token = build_test_id_token(
            secret=SECRET, iss=ISS, aud=CLIENT_ID, sub=sub, nonce=nonce,
            exp_epoch=4_102_444_800.0, fhir_user=fhir_user)  # exp year 2100

    def request(self, req):
        if req.url.endswith("/.well-known/smart-configuration"):
            return HttpResponse(200, {}, json.dumps(
                {"authorization_endpoint": AUTHORIZE, "token_endpoint": TOKEN}).encode())
        if req.url == TOKEN:
            return HttpResponse(200, {}, json.dumps({
                "access_token": "at-1", "token_type": "Bearer", "expires_in": self.expires_in,
                "patient": self.patient, "encounter": self.encounter,
                "scope": "openid fhirUser launch", "id_token": self.id_token}).encode())
        raise AssertionError(f"unexpected request {req.url}")


def _tenant() -> str:
    return str(uuid.uuid4())


def _clinician(tenant_id: str, username: str = "dr-1") -> User:
    return User.objects.create(username=username, organization_id=tenant_id, role="clinician")


def _connection(tenant_id: str):
    return embedded.register_connection(
        tenant_id=tenant_id, issuer=ISS, client_id=CLIENT_ID, redirect_uri=REDIRECT,
        vendor="epic", scopes=["openid", "fhirUser", "launch"])


# ---- service: begin_launch resolves issuer→tenant + mints a pending session ----

def test_begin_launch_resolves_tenant_and_creates_pending_session():
    t = _tenant()
    _connection(t)
    result = embedded.begin_launch(
        issuer=ISS, launch="op-123", transport=FakeEhr(),
        state_factory=lambda: "state-1", nonce_factory=lambda: "nonce-1")
    assert result["tenant_id"] == t
    assert result["authorize_url"].startswith(AUTHORIZE + "?")
    assert "state=state-1" in result["authorize_url"]
    session = EhrLaunchSession.objects.get(state="state-1")
    assert session.status == LaunchStatus.PENDING
    assert session.tenant_id == uuid.UUID(t)
    assert session.token_url == TOKEN


def test_unknown_issuer_is_refused():
    with pytest.raises(embedded.UnknownIssuerError):
        embedded.begin_launch(issuer="https://not-registered.example", launch="x",
                              transport=FakeEhr())


# ---- service: complete_launch bridges identity (the core G4 gate) ----

def _begin(t, ehr: FakeEhr, *, state="st", nonce="nn"):
    return embedded.begin_launch(issuer=ISS, launch="op", transport=ehr,
                                 state_factory=lambda: state, nonce_factory=lambda: nonce)


def test_complete_launch_bridges_identity_to_correct_user_and_audits():
    from domains.audit.models import AuditEvent
    t = _tenant()
    conn = _connection(t)
    user = _clinician(t)
    embedded.link_identity(tenant_id=t, connection_id=str(conn.id), subject=SUBJECT,
                           user_id=str(user.id))
    ehr = FakeEhr()
    _begin(t, ehr)
    ehr.stage_id_token(nonce="nn")

    result = embedded.complete_launch(state="st", code="auth-code", transport=ehr,
                                      verifier=HmacVerifier(SECRET))
    assert result["user_id"] == str(user.id)
    assert result["tenant_id"] == t
    assert result["patient"] == "Patient/abc"
    session = EhrLaunchSession.objects.get(state="st")
    assert session.status == LaunchStatus.ACTIVE
    assert session.user_id == user.id
    assert session.expires_at is not None  # bounded to the EHR token lifetime
    assert AuditEvent.objects.filter(tenant_id=t, action="ehr_launch").exists()


def test_launch_emits_ehr_launched_event():
    from core.models import DomainEventOutbox
    t = _tenant()
    conn = _connection(t)
    user = _clinician(t)
    embedded.link_identity(tenant_id=t, connection_id=str(conn.id), subject=SUBJECT,
                           user_id=str(user.id))
    ehr = FakeEhr()
    _begin(t, ehr)
    ehr.stage_id_token(nonce="nn")
    embedded.complete_launch(state="st", code="c", transport=ehr, verifier=HmacVerifier(SECRET))
    assert DomainEventOutbox.objects.filter(tenant_id=t, event_type="EhrLaunched").exists()


def test_unlinked_identity_is_refused_fail_closed():
    from core.models import DomainEventOutbox
    t = _tenant()
    _connection(t)  # no identity link created
    ehr = FakeEhr()
    _begin(t, ehr)
    ehr.stage_id_token(nonce="nn")
    with pytest.raises(embedded.IdentityBridgeDenied):
        embedded.complete_launch(state="st", code="c", transport=ehr,
                                 verifier=HmacVerifier(SECRET))
    assert EhrLaunchSession.objects.get(state="st").status == LaunchStatus.DENIED
    assert DomainEventOutbox.objects.filter(tenant_id=t, event_type="EhrLaunchDenied").exists()


def test_identity_link_does_not_cross_tenants():
    """A link in tenant A never satisfies a launch that resolved to tenant B."""
    t_a, t_b = _tenant(), _tenant()
    conn_a = _connection(t_a)
    user_a = _clinician(t_a)
    embedded.link_identity(tenant_id=t_a, connection_id=str(conn_a.id), subject=SUBJECT,
                           user_id=str(user_a.id))
    # tenant B owns a *different* issuer/connection but the same clinician subject.
    other_iss = "https://fhir.other.example/r4"
    embedded.register_connection(
        tenant_id=t_b, issuer=other_iss, client_id=CLIENT_ID, redirect_uri=REDIRECT)

    class OtherEhr(FakeEhr):
        def request(self, req):
            if req.url.startswith(other_iss):
                return HttpResponse(200, {}, json.dumps(
                    {"authorization_endpoint": AUTHORIZE, "token_endpoint": TOKEN}).encode())
            return super().request(req)

    ehr = OtherEhr()
    embedded.begin_launch(issuer=other_iss, launch="op", transport=ehr,
                          state_factory=lambda: "st-b", nonce_factory=lambda: "nn")
    # A valid id_token from tenant B's issuer, same clinician subject — but no link in B.
    ehr.id_token = build_test_id_token(
        secret=SECRET, iss=other_iss, aud=CLIENT_ID, sub="u", nonce="nn",
        exp_epoch=4_102_444_800.0, fhir_user=SUBJECT)
    with pytest.raises(embedded.IdentityBridgeDenied):
        embedded.complete_launch(state="st-b", code="c", transport=ehr,
                                 verifier=HmacVerifier(SECRET))


def test_reused_state_is_rejected():
    t = _tenant()
    conn = _connection(t)
    user = _clinician(t)
    embedded.link_identity(tenant_id=t, connection_id=str(conn.id), subject=SUBJECT,
                           user_id=str(user.id))
    ehr = FakeEhr()
    _begin(t, ehr)
    ehr.stage_id_token(nonce="nn")
    embedded.complete_launch(state="st", code="c", transport=ehr, verifier=HmacVerifier(SECRET))
    with pytest.raises(embedded.LaunchStateError):  # single-use
        embedded.complete_launch(state="st", code="c", transport=ehr,
                                 verifier=HmacVerifier(SECRET))


def test_wrong_nonce_in_id_token_is_rejected():
    """A token whose nonce does not match the launch is rejected (replay guard)."""
    t = _tenant()
    conn = _connection(t)
    user = _clinician(t)
    embedded.link_identity(tenant_id=t, connection_id=str(conn.id), subject=SUBJECT,
                           user_id=str(user.id))
    ehr = FakeEhr()
    _begin(t, ehr)
    ehr.stage_id_token(nonce="a-different-nonce")
    from clinara_integration_sdk import SmartLaunchError
    with pytest.raises(SmartLaunchError):
        embedded.complete_launch(state="st", code="c", transport=ehr,
                                 verifier=HmacVerifier(SECRET))


# ---- session liveness (expires with the EHR session) ----

def test_get_live_session_expires_and_transitions():
    from datetime import timedelta

    from django.utils import timezone
    t = _tenant()
    conn = _connection(t)
    user = _clinician(t)
    embedded.link_identity(tenant_id=t, connection_id=str(conn.id), subject=SUBJECT,
                           user_id=str(user.id))
    ehr = FakeEhr()
    ehr.expires_in = 1
    _begin(t, ehr)
    ehr.stage_id_token(nonce="nn")
    res = embedded.complete_launch(state="st", code="c", transport=ehr,
                                   verifier=HmacVerifier(SECRET))
    sid = res["session_id"]
    assert embedded.get_live_session(tenant_id=t, session_id=sid) is not None
    later = timezone.now() + timedelta(seconds=120)
    assert embedded.get_live_session(tenant_id=t, session_id=sid, now=later) is None
    assert EhrLaunchSession.objects.get(id=sid).status == LaunchStatus.EXPIRED


# ---- G5: chart-context panel ----

def test_build_context_panel_groups_labs_and_provenance():
    facts = {
        "lab.marker": "a1c", "lab.value": 8.1, "lab.unit": "%",
        "lab.ref_low": 4.0, "lab.ref_high": 5.6, "lab.prior_value": 7.4, "lab.trend": "rising",
        "patient.has_diabetes": True, "context.specialty": "endocrinology",
    }
    provenance = {
        "source_record_ids": ["msg-1"], "data_freshness_seconds": {"observation": 3600},
        "missing_facts": [], "conflicting_facts": [], "transformations": [],
        "terminology_mappings": {"LN:4548-4": "a1c"},
        "context_builder_version": "results-context-1",
    }
    panel = build_context_panel(facts=facts, provenance=provenance)
    assert panel["labs"][0]["marker"] == "a1c"
    assert panel["labs"][0]["status"] == "above_range"  # 8.1 > 5.6
    assert panel["patient_context"] == {"has_diabetes": True}
    assert panel["specialty"] == "endocrinology"
    assert panel["provenance"]["freshest_source_seconds"] == 3600
    assert panel["provenance"]["builder_version"] == "results-context-1"


def test_context_panel_service_reads_snapshot_record():
    from domains.context.services import SnapshotNotFound, chart_context_panel
    t = _tenant()
    wid = uuid.uuid4()
    ContextSnapshotRecord.objects.create(
        tenant_id=t, workflow_id=wid, patient_external_id="P1", snapshot_hash="h",
        facts={"lab.marker": "glucose", "lab.value": 65, "lab.ref_low": 70, "lab.ref_high": 99},
        provenance={"source_record_ids": ["m1"], "data_freshness_seconds": {"observation": 10},
                    "context_builder_version": "results-context-1"},
        builder_version="results-context-1")
    panel = chart_context_panel(tenant_id=t, workflow_id=str(wid))
    assert panel["labs"][0]["status"] == "below_range"  # 65 < 70
    assert panel["workflow_id"] == str(wid)
    with pytest.raises(SnapshotNotFound):
        chart_context_panel(tenant_id=t, workflow_id=str(uuid.uuid4()))


# ---- API: full launch → callback → session → context, no separate login ----

@pytest.fixture
def fake_ehr(monkeypatch):
    ehr = FakeEhr()
    monkeypatch.setattr("domains.embedded.adapters.launch_transport", lambda: ehr)
    monkeypatch.setattr("domains.embedded.adapters.launch_verifier", lambda: HmacVerifier(SECRET))
    return ehr


def test_end_to_end_launch_bridges_session_and_serves_context(fake_ehr):
    t = _tenant()
    conn = _connection(t)
    user = _clinician(t, username="dr-embedded")
    embedded.link_identity(tenant_id=t, connection_id=str(conn.id), subject=SUBJECT,
                           user_id=str(user.id))
    client = APIClient()

    # 1) EHR launch → 302 to the EHR authorize endpoint carrying our state.
    launch = client.get(f"/api/v1/smart/launch?iss={ISS}&launch=op-xyz")
    assert launch.status_code == 302
    state = parse_qs(urlparse(launch["Location"]).query)["state"][0]

    # 2) The EHR echoes our nonce into the id_token, then redirects back to the callback.
    nonce = EhrLaunchSession.objects.get(state=state).nonce
    fake_ehr.stage_id_token(nonce=nonce)
    callback = client.get(f"/api/v1/smart/callback?state={state}&code=auth-code")
    assert callback.status_code == 302
    assert callback["Location"].startswith("/embedded/")

    # 3) No separate login: the session is already established — whoami is the bridged user.
    session = client.get("/api/v1/embedded/session")
    assert session.status_code == 200
    assert session.data["embedded"] is True
    assert session.data["username"] == "dr-embedded"
    assert session.data["launch"]["patient"] == "Patient/abc"

    # 4) Chart-context panel for an item in the review queue.
    wid = uuid.uuid4()
    ContextSnapshotRecord.objects.create(
        tenant_id=t, workflow_id=wid, patient_external_id="P1", snapshot_hash="h",
        facts={"lab.marker": "a1c", "lab.value": 8.1, "lab.ref_low": 4.0, "lab.ref_high": 5.6},
        provenance={"data_freshness_seconds": {"observation": 60},
                    "context_builder_version": "results-context-1"},
        builder_version="results-context-1")
    panel = client.get(f"/api/v1/embedded/context/{wid}")
    assert panel.status_code == 200
    assert panel.data["labs"][0]["status"] == "above_range"


def test_launch_requires_iss_and_launch(fake_ehr):
    assert APIClient().get("/api/v1/smart/launch").status_code == 400


def test_launch_unknown_issuer_is_forbidden(fake_ehr):
    resp = APIClient().get("/api/v1/smart/launch?iss=https://nope.example&launch=x")
    assert resp.status_code == 403


def test_callback_denies_unlinked_identity(fake_ehr):
    t = _tenant()
    _connection(t)  # no identity link
    client = APIClient()
    launch = client.get(f"/api/v1/smart/launch?iss={ISS}&launch=op")
    state = parse_qs(urlparse(launch["Location"]).query)["state"][0]
    fake_ehr.stage_id_token(nonce=EhrLaunchSession.objects.get(state=state).nonce)
    resp = client.get(f"/api/v1/smart/callback?state={state}&code=c")
    assert resp.status_code == 403


def test_context_endpoint_requires_auth():
    resp = APIClient().get(f"/api/v1/embedded/context/{uuid.uuid4()}")
    assert resp.status_code in (401, 403)


# ---- marketplace manifests ----

def test_marketplace_manifests_are_valid():
    from pathlib import Path

    from django.conf import settings

    from domains.embedded.marketplace import load_manifests, validate_manifest
    manifest_dir = Path(settings.BASE_DIR).parent.parent / "clinical" / "marketplace"
    manifests = load_manifests(manifest_dir)
    assert {"epic-showroom", "athena-marketplace"} <= set(manifests)
    for name, manifest in manifests.items():
        assert validate_manifest(manifest) == [], f"{name} invalid"


def test_validator_flags_missing_launch_scope():
    from domains.embedded.marketplace import validate_manifest
    bad = {"app_name": "X", "vendor": "epic", "launch_url": "https://a/l",
           "redirect_uris": ["https://a/c"], "scopes": ["openid", "fhirUser"],
           "fhir_version": "4.0.1", "launch_type": "ehr"}
    errors = validate_manifest(bad)
    assert any("launch" in e for e in errors)
