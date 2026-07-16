"""Refill API (plan Phase 4; spec §6.3, §6.3.6) — ingest, inbox, review actions over HTTP."""
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
    user = User.objects.create(username="nurse1", organization_id=tenant_id, role="nurse")
    api = APIClient()
    api.force_authenticate(user=user)
    return api


def _payload(code="617314", **over):
    p = {"patient_external_id": "P1", "code_system": "RXNORM", "code": code,
         "requested_dose": "10 MG", "days_since_last_fill": 80, "days_supply": 90}
    p.update(over)
    return p


def test_ingest_and_review_flow(client):
    resp = client.post("/api/v1/refills/ingest", _payload(), format="json")
    assert resp.status_code == 201
    assert resp.data["workflow"]["outcome"] == "one_click_prepared"

    listing = client.get("/api/v1/refills")
    wid = listing.data["results"][0]["id"]
    detail = client.get(f"/api/v1/refills/{wid}")
    assert detail.status_code == 200
    assert detail.data["clinical_factors_used"]  # traceability surfaced

    approved = client.post(f"/api/v1/refills/{wid}/approve", {}, format="json")
    assert approved.status_code == 200
    assert approved.data["status"] == "approved"


def test_controlled_substance_shows_escalation(client):
    resp = client.post("/api/v1/refills/ingest", _payload(code="1049221"), format="json")
    assert resp.data["workflow"]["outcome"] == "escalate_controlled_substance"
    assert resp.data["workflow"]["controlled_substance"] is True


def test_missing_field_returns_400(client):
    resp = client.post("/api/v1/refills/ingest", {"code": "617314"}, format="json")
    assert resp.status_code == 400


def test_requires_authentication():
    anon = APIClient()
    assert anon.get("/api/v1/refills").status_code in (401, 403)
