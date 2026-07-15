"""Phase 3 API — gateway, monitoring, dead-letter replay, delivery, SMART launch (spec §6.7)."""
import uuid

import pytest
from rest_framework.test import APIClient

from domains.identity.models import User

pytestmark = pytest.mark.django_db

ORU = (
    "MSH|^~\\&|LIS|GENERAL|CLINARA|CLINARA|20260710090000||ORU^R01|MSG1|P|2.5\r"
    "PID|1||P123^^^HOSP^MR||DOE^JANE\r"
    "OBX|1|NM|4548-4^Hemoglobin A1c^LN||7.8|%|||||F|||20260710091500\r"
)


@pytest.fixture
def tenant_id() -> str:
    return str(uuid.uuid4())


@pytest.fixture
def client(tenant_id) -> APIClient:
    user = User.objects.create(
        username="integrator", organization_id=tenant_id, role="integration_engineer"
    )
    api = APIClient()
    api.force_authenticate(user=user)
    return api


def _register(client, kind="hl7v2", **extra):
    body = {"name": f"lab-{kind}", "kind": kind, **extra}
    resp = client.post("/api/v1/integrations", body, format="json")
    assert resp.status_code == 201
    return resp.data["id"]


def test_register_and_receive_hl7_over_http(client):
    iid = _register(client)
    resp = client.post(f"/api/v1/integrations/{iid}/receive", {"hl7": ORU}, format="json")
    assert resp.status_code == 201
    assert resp.data["status"] == "processed"

    health = client.get(f"/api/v1/integrations/{iid}/health")
    assert health.status_code == 200
    assert health.data["throughput"] >= 1


def test_malformed_message_dead_letters_and_replays(client):
    iid = _register(client)
    resp = client.post(f"/api/v1/integrations/{iid}/receive", {"hl7": "garbage"}, format="json")
    assert resp.status_code == 202
    assert resp.data["status"] == "dead_lettered"
    dl_id = resp.data["dead_letter_id"]

    replay = client.post(f"/api/v1/dead-letters/{dl_id}/replay", {}, format="json")
    assert replay.status_code == 200
    assert replay.data["status"] == "open"  # still unprocessable, never lost


def test_dashboard_and_scan_gaps(client):
    iid = _register(client, expected_interval_seconds=1)
    client.post(f"/api/v1/integrations/{iid}/receive", {"hl7": ORU}, format="json")
    board = client.get("/api/v1/integrations/dashboard")
    assert board.status_code == 200
    assert len(board.data["interfaces"]) == 1


def test_write_back_and_deliver(client):
    wid = str(uuid.uuid4())
    wb = client.post(f"/api/v1/workflows/{wid}/write-back",
                     {"channel": "ehr_task", "target": "care_team"}, format="json")
    assert wb.status_code == 201
    mid = wb.data["id"]
    delivered = client.post(f"/api/v1/outbound/{mid}/deliver", {}, format="json")
    assert delivered.status_code == 200
    assert delivered.data["status"] == "delivered"


def test_smart_launch_returns_embedded_context(client):
    resp = client.get("/api/v1/smart/launch?patient=P123")
    assert resp.status_code == 200
    assert resp.data["embedded"] is True
    assert resp.data["patient"] == "P123"


def test_requires_authentication():
    anon = APIClient()
    assert anon.get("/api/v1/integrations").status_code in (401, 403)
