"""API v1 tests (plan Phase 1; spec §6.10.1 clinician view).

Exercises ingestion (simplified + FHIR), the clinician inbox list/detail, and the
approve/replay actions over HTTP with an authenticated, tenant-scoped user.
"""
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
    user = User.objects.create(
        username="clinician1", organization_id=tenant_id, role="clinician"
    )
    api = APIClient()
    api.force_authenticate(user=user)
    return api


def _simplified(**over):
    p = {
        "patient_external_id": "P1", "code_system": "LOINC", "code": "4548-4",
        "value": 7.8, "unit": "%", "observed_at": "2026-07-10T09:00:00+00:00",
        "patient_facts": {"patient.has_diabetes": True}, "specialty": "primary_care",
    }
    p.update(over)
    return p


def test_ingest_simplified_payload(client):
    resp = client.post("/api/v1/results/ingest", _simplified(), format="json")
    assert resp.status_code == 201
    assert resp.data["status"] == "processed"
    assert resp.data["workflow"]["classification"] == "clinician_review_required"


def test_ingest_fhir_observation(client):
    fhir = {
        "resourceType": "Observation",
        "subject": {"reference": "Patient/P9"},
        "code": {"coding": [{"system": "http://loinc.org", "code": "2823-3"}]},
        "valueQuantity": {"value": 6.8, "unit": "mmol/L"},
        "effectiveDateTime": "2026-07-10T09:00:00+00:00",
    }
    resp = client.post("/api/v1/results/ingest", fhir, format="json")
    assert resp.status_code == 201
    assert resp.data["workflow"]["classification"] == "critical_escalation"


def test_unknown_code_returns_queued(client):
    resp = client.post("/api/v1/results/ingest", _simplified(code="9999-9"), format="json")
    assert resp.status_code == 202
    assert resp.data["status"] == "queued_or_duplicate"


def test_list_and_detail_and_actions(client):
    client.post("/api/v1/results/ingest", _simplified(), format="json")
    listing = client.get("/api/v1/workflows")
    assert listing.status_code == 200
    assert len(listing.data["results"]) == 1
    wid = listing.data["results"][0]["id"]

    detail = client.get(f"/api/v1/workflows/{wid}")
    assert detail.status_code == 200
    # Clinician view surfaces the required fields (spec §6.10.1).
    assert detail.data["reason_codes"] == ["A1C_ABOVE_CONFIGURED_TARGET"]
    assert detail.data["communication"]["validation_passed"] is True
    assert "approve" in detail.data["available_actions"]

    approved = client.post(f"/api/v1/workflows/{wid}/approve", {}, format="json")
    assert approved.status_code == 200
    assert approved.data["status"] == "approved"

    replay = client.post(f"/api/v1/workflows/{wid}/replay", {}, format="json")
    assert replay.status_code == 200
    assert replay.data["matches"] is True


def test_tenant_scoping_hides_other_tenants_workflows(tenant_id):
    # Tenant A ingests; tenant B must not see it (app-layer scope; RLS on Postgres).
    ua = User.objects.create(username="a", organization_id=tenant_id, role="clinician")
    a = APIClient()
    a.force_authenticate(user=ua)
    a.post("/api/v1/results/ingest", _simplified(), format="json")

    ub = User.objects.create(username="b", organization_id=str(uuid.uuid4()), role="clinician")
    b = APIClient()
    b.force_authenticate(user=ub)
    assert b.get("/api/v1/workflows").data["results"] == []


def test_requires_authentication():
    anon = APIClient()
    assert anon.get("/api/v1/workflows").status_code in (401, 403)
