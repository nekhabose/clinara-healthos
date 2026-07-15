"""Phase 9 — Billing & Coding Intelligence over HTTP (plan Phase 9; closes G1)."""
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
    user = User.objects.create(username="dr-coder", organization_id=tenant_id, role="clinician")
    api = APIClient()
    api.force_authenticate(user=user)
    return api


def _analyze(client):
    return client.post("/api/v1/coding/analyze", {
        "patient_external_id": "pat-1", "encounter_id": "enc-1",
        "lab_values": {"egfr": 25.0},
        "encounter_dx": [{"code": "N18.9", "description": "CKD unspecified"}],
    }, format="json")


def test_analyze_review_confirm_export_flow(client):
    resp = _analyze(client)
    assert resp.status_code == 201
    results = resp.data["results"]
    assert results, "expected suggestions"
    assert all(r["status"] == "pending" for r in results)
    assert all(r["evidence"] for r in results)  # evidence-linked

    # Review queue is queryable and pending.
    listing = client.get("/api/v1/coding/suggestions?status=pending")
    assert listing.status_code == 200
    sid = listing.data["results"][0]["id"]

    # Export is blocked before confirmation.
    blocked = client.post(f"/api/v1/coding/suggestions/{sid}/export", {}, format="json")
    assert blocked.status_code == 409

    confirmed = client.post(f"/api/v1/coding/suggestions/{sid}/confirm",
                            {"reason": "supported"}, format="json")
    assert confirmed.status_code == 200
    assert confirmed.data["status"] == "confirmed"

    exported = client.post(f"/api/v1/coding/suggestions/{sid}/export", {}, format="json")
    assert exported.status_code == 200
    assert exported.data["status"] == "exported"


def test_reject_flow(client):
    _analyze(client)
    sid = client.get("/api/v1/coding/suggestions").data["results"][0]["id"]
    rejected = client.post(f"/api/v1/coding/suggestions/{sid}/reject",
                           {"reason": "not supported"}, format="json")
    assert rejected.status_code == 200
    assert rejected.data["status"] == "rejected"


def test_analyze_requires_patient_or_workflow(client):
    resp = client.post("/api/v1/coding/analyze", {"lab_values": {"egfr": 25.0}}, format="json")
    assert resp.status_code == 400


def test_requires_authentication():
    anon = APIClient()
    assert anon.get("/api/v1/coding/suggestions").status_code in (401, 403)
