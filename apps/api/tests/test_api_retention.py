"""Phase 11 — Data Lifecycle & Compliance Hardening over HTTP (closes G7)."""
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from rest_framework.test import APIClient

from domains.identity.models import User

pytestmark = pytest.mark.django_db


@pytest.fixture
def tenant_id() -> str:
    return str(uuid.uuid4())


@pytest.fixture
def client(tenant_id) -> APIClient:
    user = User.objects.create(username="ops", organization_id=tenant_id, role="clinician")
    api = APIClient()
    api.force_authenticate(user=user)
    return api


@pytest.fixture
def admin_client(tenant_id) -> APIClient:
    user = User.objects.create(username="admin", organization_id=tenant_id,
                               role="tenant_administrator")
    api = APIClient()
    api.force_authenticate(user=user)
    return api


def _make_expired_inbound(tenant_id: str):
    from domains.integrations.models import InboundMessage
    msg = InboundMessage.objects.create(
        tenant_id=tenant_id, source="fhir", message_type="Observation",
        idempotency_key=f"idem-{uuid.uuid4()}", raw_payload={"phi": "x"},
    )
    old = datetime.now(UTC) - timedelta(days=200)
    InboundMessage.objects.filter(id=msg.id).update(created_at=old)
    return msg


def test_policy_lists_windows_and_categories(client):
    resp = client.get("/api/v1/retention/policy")
    assert resp.status_code == 200
    assert resp.data["windows"]["raw_inbound"] == 90
    assert resp.data["terminated"] is False
    keys = {c["key"] for c in resp.data["categories"]}
    assert "raw_inbound" in keys and "observations" in keys


def test_set_window_and_reflect(client):
    resp = client.put("/api/v1/retention/policy/window",
                      {"category": "raw_inbound", "days": 30}, format="json")
    assert resp.status_code == 200
    assert resp.data["overrides"]["raw_inbound"] == 30
    assert client.get("/api/v1/retention/policy").data["windows"]["raw_inbound"] == 30


def test_set_window_rejects_bad_input(client):
    bad = client.put("/api/v1/retention/policy/window",
                     {"category": "raw_inbound", "days": 0}, format="json")
    assert bad.status_code == 422
    unknown = client.put("/api/v1/retention/policy/window",
                         {"category": "nope", "days": 30}, format="json")
    assert unknown.status_code == 422
    missing = client.put("/api/v1/retention/policy/window", {"days": 30}, format="json")
    assert missing.status_code == 400


def test_purge_flow_dry_run_then_real(client, tenant_id):
    from domains.integrations.models import InboundMessage

    _make_expired_inbound(tenant_id)
    dry = client.post("/api/v1/retention/purge", {"dry_run": True}, format="json")
    assert dry.status_code == 201
    assert dry.data["dry_run"] is True and dry.data["total_purged"] == 1
    assert InboundMessage.objects.filter(tenant_id=tenant_id).count() == 1  # not deleted

    real = client.post("/api/v1/retention/purge", {}, format="json")
    assert real.status_code == 201
    assert real.data["total_purged"] == 1
    assert InboundMessage.objects.filter(tenant_id=tenant_id).count() == 0

    runs = client.get("/api/v1/retention/runs")
    assert runs.status_code == 200
    assert len(runs.data["results"]) == 2


def test_terminate_requires_admin_role(client):
    forbidden = client.post("/api/v1/retention/terminate", {"reason": "x"}, format="json")
    assert forbidden.status_code == 403


def test_terminate_issues_certificate_for_admin(admin_client, tenant_id):
    from domains.integrations.models import InboundMessage

    _make_expired_inbound(tenant_id)
    resp = admin_client.post("/api/v1/retention/terminate",
                             {"reason": "contract ended"}, format="json")
    assert resp.status_code == 201
    assert resp.data["mode"] == "termination"
    assert len(resp.data["content_hash"]) == 64
    assert InboundMessage.objects.filter(tenant_id=tenant_id).count() == 0

    cert = admin_client.get("/api/v1/retention/certificate")
    assert cert.status_code == 200
    assert cert.data["content_hash"] == resp.data["content_hash"]


def test_certificate_404_when_none(client):
    assert client.get("/api/v1/retention/certificate").status_code == 404


def test_requires_authentication():
    anon = APIClient()
    assert anon.get("/api/v1/retention/policy").status_code in (401, 403)
