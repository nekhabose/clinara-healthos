"""Tenant-isolation regression harness (plan §2, Phase 0 exit gate).

This is the PERMANENT, ever-growing gate: any cross-tenant read or write is a
release-blocking failure. It is a placeholder until the RLS-enabled clinical tables land
(Phase 1) and the non-superuser test DB role is provisioned in CI.

Intended assertions (to implement as tables arrive):
  - A session pinned to tenant A cannot SELECT tenant B's rows.
  - A session pinned to tenant A cannot INSERT/UPDATE rows carrying tenant B's id.
  - A session with NULL app.current_tenant sees no tenant-scoped rows.
  - The app DB role is not a superuser and does not own the tables (RLS would be bypassed).
"""
import pytest

pytestmark = pytest.mark.skip(
    reason="Enable once RLS clinical tables (Phase 1) and the non-superuser CI DB role exist."
)


def test_cross_tenant_select_is_blocked():
    ...


def test_cross_tenant_write_is_blocked():
    ...


def test_null_tenant_sees_nothing():
    ...
