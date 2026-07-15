"""Phase 10 — Specialty Protocol Breadth over HTTP (plan Phase 10; closes G6)."""
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
    user = User.objects.create(username="dr-endo", organization_id=tenant_id, role="clinician")
    api = APIClient()
    api.force_authenticate(user=user)
    return api


def test_registry_lists_30_plus_specialties_all_covered(client):
    resp = client.get("/api/v1/specialties")
    assert resp.status_code == 200
    assert resp.data["coverage"]["registered"] >= 30
    assert resp.data["coverage"]["uncovered"] == []
    assert all(s["covered"] for s in resp.data["results"])


def test_packs_are_listed_and_all_validate(client):
    resp = client.get("/api/v1/specialties/packs")
    assert resp.status_code == 200
    assert resp.data["results"]
    for pack in resp.data["results"]:
        assert pack["validation"]["ok"] is True
        assert pack["validation"]["safety_ok"] is True


def test_pack_detail_shows_effective_thresholds(client):
    resp = client.get("/api/v1/specialties/packs/thyroid")
    assert resp.status_code == 200
    assert resp.data["key"] == "thyroid"
    assert resp.data["effective_thresholds"]["tsh_upper"] == 4.5
    assert resp.data["overrides"] == {}


def test_unknown_pack_is_404(client):
    assert client.get("/api/v1/specialties/packs/nope").status_code == 404


def test_set_threshold_customizes_without_code_change(client):
    resp = client.post("/api/v1/specialties/packs/thyroid/thresholds",
                       {"parameter": "tsh_upper", "value": 4.0}, format="json")
    assert resp.status_code == 200
    assert resp.data["effective_thresholds"]["tsh_upper"] == 4.0
    assert resp.data["overrides"] == {"tsh_upper": 4.0}


def test_unsafe_threshold_is_rejected_422(client):
    # tsh_upper = 7.0 breaks the subclinical required test case → gate refuses.
    resp = client.post("/api/v1/specialties/packs/thyroid/thresholds",
                       {"parameter": "tsh_upper", "value": 7.0}, format="json")
    assert resp.status_code == 422


def test_missing_body_is_400(client):
    resp = client.post("/api/v1/specialties/packs/thyroid/thresholds", {}, format="json")
    assert resp.status_code == 400


def test_reset_restores_defaults(client):
    client.post("/api/v1/specialties/packs/thyroid/thresholds",
                {"parameter": "tsh_upper", "value": 4.0}, format="json")
    resp = client.post("/api/v1/specialties/packs/thyroid/thresholds/reset", {}, format="json")
    assert resp.status_code == 200
    assert resp.data["overrides"] == {}
    assert resp.data["effective_thresholds"]["tsh_upper"] == 4.5
