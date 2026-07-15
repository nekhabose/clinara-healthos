"""Tenant-isolation regression harness (plan §2, Phase 0/1 exit gate).

The PERMANENT, ever-growing gate: any cross-tenant read or write is release-blocking.

Two layers are asserted:
  * **App-layer scoping** (runs everywhere, incl. SQLite): services/queries filter by
    ``tenant_id`` — covered directly here and in ``test_api`` /``test_results_workflow``.
  * **PostgreSQL RLS** (runs only on Postgres with a NON-superuser role): the database
    itself blocks cross-tenant rows even if app code is buggy. These tests skip on SQLite
    and when connected as a superuser (superusers bypass RLS), so they are meaningful only
    in the dockerized/CI Postgres run with the ``clinara_app`` role.
"""
from __future__ import annotations

import uuid

import pytest
from django.db import connection
from django.db.utils import Error as DatabaseError

from clinara.middleware.tenant import current_tenant_id, set_db_tenant
from domains.clinical_data.models import PatientReference

pytestmark = pytest.mark.django_db


def _skip_unless_rls() -> None:
    """Skip unless the DB enforces RLS for this connection (Postgres, non-superuser)."""
    if connection.vendor != "postgresql":
        pytest.skip("RLS assertions require PostgreSQL (SQLite has no RLS).")
    with connection.cursor() as cur:
        cur.execute("SELECT current_setting('is_superuser')")
        if cur.fetchone()[0] != "off":
            pytest.skip("Connected as superuser — RLS is bypassed; use the clinara_app role.")


def _make_patient(tenant_id: str, external_id: str) -> None:
    current_tenant_id.set(tenant_id)
    set_db_tenant(tenant_id)
    PatientReference.objects.create(tenant_id=tenant_id, external_id=external_id)


# ---- App-layer scoping (runs on every backend) ----

def test_app_layer_queries_are_tenant_scoped():
    a, b = str(uuid.uuid4()), str(uuid.uuid4())
    _make_patient(a, "PA")
    _make_patient(b, "PB")
    assert PatientReference.objects.filter(tenant_id=a).count() == 1
    assert PatientReference.objects.filter(tenant_id=a, external_id="PB").count() == 0


# ---- Database-enforced RLS (Postgres, non-superuser only) ----


def test_cross_tenant_select_is_blocked():
    _skip_unless_rls()
    a, b = str(uuid.uuid4()), str(uuid.uuid4())
    _make_patient(a, "PA")
    set_db_tenant(b)
    assert PatientReference.objects.count() == 0  # A's row invisible to B
    set_db_tenant(a)
    assert PatientReference.objects.count() == 1



def test_cross_tenant_write_is_blocked():
    _skip_unless_rls()
    a, b = str(uuid.uuid4()), str(uuid.uuid4())
    set_db_tenant(b)
    with pytest.raises(DatabaseError):  # WITH CHECK violation
        PatientReference.objects.create(tenant_id=a, external_id="PA")



def test_null_tenant_sees_nothing():
    _skip_unless_rls()
    a = str(uuid.uuid4())
    _make_patient(a, "PA")
    set_db_tenant(None)
    assert PatientReference.objects.count() == 0
