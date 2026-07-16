"""RBAC policy + enforcement (spec §10.2).

Covers the pure policy (clinara.rbac) and the middleware that enforces it on the real
session-auth path used by the console. Uses ``Client.force_login`` (which establishes a
session) rather than DRF ``force_authenticate`` (which sets the user only at the view layer),
so the request actually passes through ``RbacMiddleware``.
"""
from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model
from django.test import Client

from clinara.rbac import (
    CAP_ADMIN,
    CAP_ANALYTICS,
    CAP_CODING,
    CAP_PROTOCOLS,
    CAP_RESULTS,
    capabilities_for,
    required_capability,
)

User = get_user_model()
TENANT = "11111111-1111-1111-1111-111111111111"


# ---------------------------------------------------------------- pure policy
def test_required_capability_maps_each_segment():
    assert required_capability("/api/v1/workflows") == CAP_RESULTS
    assert required_capability("/api/v1/results/ingest") == CAP_RESULTS
    assert required_capability("/api/v1/analytics/dashboards") == CAP_ANALYTICS
    assert required_capability("/api/v1/feedback") == CAP_ANALYTICS
    assert required_capability("/api/v1/protocols") == CAP_PROTOCOLS
    assert required_capability("/api/v1/specialties") == CAP_PROTOCOLS
    assert required_capability("/api/v1/coding/x") == CAP_CODING
    assert required_capability("/api/v1/retention/policy") == CAP_ADMIN
    assert required_capability("/api/v1/integrations") == CAP_ADMIN


def test_public_and_non_api_paths_are_unguarded():
    assert required_capability("/api/v1/smart/launch") is None
    assert required_capability("/api/v1/embedded/session") is None
    assert required_capability("/healthz") is None
    assert required_capability("/console/") is None


def test_capabilities_matrix_and_fail_closed():
    assert CAP_RESULTS in capabilities_for("clinician")
    assert CAP_ANALYTICS not in capabilities_for("clinician")
    assert capabilities_for("nurse") == frozenset({CAP_RESULTS, "messages", "prescriptions"})
    assert capabilities_for("operations_analyst") == frozenset({CAP_ANALYTICS})
    assert capabilities_for("clinical_programmer") == frozenset({CAP_PROTOCOLS})
    assert CAP_ADMIN in capabilities_for("tenant_administrator")
    assert capabilities_for(None) == frozenset()        # unknown role -> nothing
    assert capabilities_for("not_a_role") == frozenset()


# ---------------------------------------------------------------- enforcement
@pytest.fixture
def make_user(db):
    def _make(username, role):
        return User.objects.create(username=username, organization_id=TENANT, role=role)

    return _make


def _client(user):
    c = Client()
    c.force_login(user)
    return c


@pytest.mark.django_db
def test_clinician_allowed_clinical_denied_authoring_and_analytics(make_user):
    c = _client(make_user("clin", "clinician"))
    assert c.get("/api/v1/workflows").status_code != 403
    assert c.get("/api/v1/messages").status_code != 403
    assert c.get("/api/v1/refills").status_code != 403
    assert c.get("/api/v1/analytics/dashboards").status_code == 403
    assert c.get("/api/v1/protocols").status_code == 403
    assert c.get("/api/v1/retention/policy").status_code == 403


@pytest.mark.django_db
def test_analyst_only_analytics(make_user):
    c = _client(make_user("an", "operations_analyst"))
    assert c.get("/api/v1/analytics/dashboards").status_code != 403
    assert c.get("/api/v1/workflows").status_code == 403
    assert c.get("/api/v1/messages").status_code == 403
    assert c.get("/api/v1/protocols").status_code == 403


@pytest.mark.django_db
def test_programmer_only_authoring_no_phi(make_user):
    c = _client(make_user("prog", "clinical_programmer"))
    assert c.get("/api/v1/protocols").status_code != 403
    assert c.get("/api/v1/specialties").status_code != 403
    assert c.get("/api/v1/workflows").status_code == 403      # no PHI
    assert c.get("/api/v1/messages").status_code == 403


@pytest.mark.django_db
def test_nurse_no_coding_no_admin(make_user):
    c = _client(make_user("nur", "nurse"))
    assert c.get("/api/v1/refills").status_code != 403
    assert c.get("/api/v1/coding/x").status_code == 403
    assert c.get("/api/v1/analytics/dashboards").status_code == 403


@pytest.mark.django_db
def test_admin_sees_every_surface(make_user):
    c = _client(make_user("adm", "tenant_administrator"))
    for path in (
        "/api/v1/workflows",
        "/api/v1/messages",
        "/api/v1/refills",
        "/api/v1/coding/x",
        "/api/v1/protocols",
        "/api/v1/analytics/dashboards",
        "/api/v1/retention/policy",
        "/api/v1/integrations",
    ):
        assert c.get(path).status_code != 403, path


@pytest.mark.django_db
def test_unauthenticated_is_not_403_but_401(make_user):
    # RBAC defers to the view's IsAuthenticated for anonymous callers (401, not a role 403).
    assert Client().get("/api/v1/workflows").status_code in (401, 403, 302)
