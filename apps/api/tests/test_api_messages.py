"""Patient message API (plan Phase 5; spec §6.2) — ingest, inbox, review over HTTP."""
import uuid

import pytest
from rest_framework.test import APIClient

from domains.identity.models import User

pytestmark = pytest.mark.django_db


@pytest.fixture
def tenant_id() -> str:
    return str(uuid.uuid4())


@pytest.fixture
def client(tenant_id) -> APIClient:
    user = User.objects.create(username="triage_nurse", organization_id=tenant_id, role="nurse")
    api = APIClient()
    api.force_authenticate(user=user)
    return api


def test_emergency_message_escalates_over_http(client):
    resp = client.post("/api/v1/messages/ingest",
                       {"patient_external_id": "P1", "text": "I have crushing chest pain"},
                       format="json")
    assert resp.status_code == 201
    assert resp.data["message"]["urgency"] == "emergency"
    assert resp.data["message"]["destination"] == "emergency_escalation"


def test_inbox_and_detail_and_respond(client):
    client.post("/api/v1/messages/ingest",
                {"patient_external_id": "P1", "text": "question about my bill"}, format="json")
    listing = client.get("/api/v1/messages")
    mid = listing.data["results"][0]["id"]
    detail = client.get(f"/api/v1/messages/{mid}")
    assert detail.status_code == 200
    assert "respond" in detail.data["available_actions"]
    resolved = client.post(f"/api/v1/messages/{mid}/resolve", {}, format="json")
    assert resolved.data["status"] == "resolved"


def test_contamination_returns_409(client):
    resp = client.post("/api/v1/messages/ingest",
                       {"patient_external_id": "P1", "text": "headache",
                        "context_patient_id": "P2"}, format="json")
    assert resp.status_code == 409
    assert resp.data["contamination_blocked"] is True


def test_missing_field_returns_400(client):
    resp = client.post("/api/v1/messages/ingest", {"patient_external_id": "P1"}, format="json")
    assert resp.status_code == 400


def test_requires_authentication():
    anon = APIClient()
    assert anon.get("/api/v1/messages").status_code in (401, 403)
