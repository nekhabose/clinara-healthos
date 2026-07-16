"""Rule Studio API (plan Phase 2; spec §6.5) — the no-code-change authoring flow over HTTP.

Drives the full lifecycle through the REST surface a clinical programmer would use: create
protocol → author version → attach test → simulate → impact → submit → dual-approve →
deploy → roll back. No application deploy happens anywhere in this test.
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
        username="programmer1", organization_id=tenant_id, role="clinical_programmer"
    )
    api = APIClient()
    api.force_authenticate(user=user)
    return api


RULE_BODY = {
    "id": "a1c_above_target", "version": 1, "marker": "hemoglobin_a1c",
    "scope": {"specialties": ["primary_care"]},
    "when": {"all": [
        {"fact": "patient.has_diabetes", "operator": "equals", "value": True},
        {"fact": "lab.a1c", "operator": "greater_than_or_equal", "value": 7.0},
    ]},
    "then": {"classification": "clinician_review_required",
             "recommended_action": "evaluate_current_plan",
             "reason_codes": ["A1C_ABOVE_CONFIGURED_TARGET"]},
    "safety": {"excluded_when": ["patient.pregnancy"]},
}


def _author(client):
    p = client.post("/api/v1/protocols",
                    {"key": "a1c-mgmt", "marker": "hemoglobin_a1c", "title": "A1C"},
                    format="json")
    assert p.status_code == 201
    v = client.post(f"/api/v1/protocols/{p.data['id']}/versions",
                    {"rule_body": RULE_BODY}, format="json")
    assert v.status_code == 201
    vid = v.data["id"]
    client.post(f"/api/v1/protocol-versions/{vid}/test-cases", {
        "name": "above_target", "marker": "hemoglobin_a1c", "specialty": "primary_care",
        "facts": {"lab.a1c": 7.8, "patient.has_diabetes": True},
        "expected_classification": "clinician_review_required",
    }, format="json")
    return vid


def test_full_studio_flow_over_http(client):
    vid = _author(client)

    sim = client.post(f"/api/v1/protocol-versions/{vid}/simulate", {}, format="json")
    assert sim.status_code == 200
    assert sim.data["scenario_count"] == 1

    impact = client.post(f"/api/v1/protocol-versions/{vid}/impact", {}, format="json")
    assert impact.status_code == 200
    assert impact.data["safe_to_activate"] is True

    client.post(f"/api/v1/protocol-versions/{vid}/submit", {}, format="json")
    client.post(f"/api/v1/protocol-versions/{vid}/approve", {"role": "clinical"}, format="json")
    approved = client.post(f"/api/v1/protocol-versions/{vid}/approve",
                           {"role": "engineering"}, format="json")
    assert approved.data["state"] == "approved"
    assert approved.data["dual_approved"] is True

    deploy = client.post(f"/api/v1/protocol-versions/{vid}/deploy",
                         {"mode": "progressive", "rollout_percentage": 50}, format="json")
    assert deploy.status_code == 201
    assert deploy.data["status"] == "active"

    bundle = client.get(f"/api/v1/protocol-versions/{vid}/bundle")
    assert bundle.status_code == 200
    assert bundle.data["approval"]["dual_approved"] is True

    rb = client.post(f"/api/v1/deployments/{deploy.data['id']}/rollback",
                     {"reason": "manual"}, format="json")
    assert rb.status_code == 200


def test_deploy_without_approval_returns_422(client):
    vid = _author(client)
    resp = client.post(f"/api/v1/protocol-versions/{vid}/deploy",
                       {"mode": "progressive"}, format="json")
    assert resp.status_code == 422
    assert resp.data["activation_blocked"] is True


def test_malformed_rule_body_returns_400(client):
    p = client.post("/api/v1/protocols",
                    {"key": "bad", "marker": "hemoglobin_a1c", "title": "bad"}, format="json")
    resp = client.post(f"/api/v1/protocols/{p.data['id']}/versions",
                       {"rule_body": {"id": "x"}}, format="json")  # missing required fields
    assert resp.status_code == 400


def test_requires_authentication():
    anon = APIClient()
    assert anon.get("/api/v1/protocols").status_code in (401, 403)
