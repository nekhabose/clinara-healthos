"""Analytics & personalization API (plan Phase 6; spec §12) — the governed loop over HTTP."""
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
    user = User.objects.create(username="analyst", organization_id=tenant_id,
                               role="operations_analyst")
    api = APIClient()
    api.force_authenticate(user=user)
    return api


def _seed_edits(client, n=4):
    for _ in range(n):
        client.post("/api/v1/feedback", {
            "workflow_type": "results", "workflow_id": str(uuid.uuid4()),
            "practitioner": "dr_smith", "action": "edit",
            "original_text": "the quick brown fox jumps over", "edited_text": "the fox",
        }, format="json")


def test_capture_dashboards_and_governed_recommendation(client):
    _seed_edits(client)
    board = client.get("/api/v1/analytics/dashboards")
    assert board.status_code == 200
    assert board.data["executive"]["total_decisions"] == 4

    derived = client.post("/api/v1/analytics/preferences/derive",
                          {"practitioner": "dr_smith"}, format="json")
    assert derived.status_code == 201
    assert derived.data["status"] == "pending"
    rid = derived.data["id"]

    # Inert until approved.
    listing = client.get("/api/v1/analytics/recommendations?status=pending")
    assert any(r["id"] == rid for r in listing.data["results"])

    approved = client.post(f"/api/v1/analytics/recommendations/{rid}/approve", {}, format="json")
    assert approved.status_code == 200
    assert approved.data["status"] == "approved"


def test_insufficient_signal_returns_no_recommendation(client):
    resp = client.post("/api/v1/analytics/preferences/derive",
                       {"practitioner": "nobody"}, format="json")
    assert resp.status_code == 200
    assert resp.data["status"] == "insufficient_signal"


def test_requires_authentication():
    anon = APIClient()
    assert anon.get("/api/v1/analytics/dashboards").status_code in (401, 403)
