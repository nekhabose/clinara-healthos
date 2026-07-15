"""Row-Level Security helpers.

Use ``enable_rls`` inside a data migration for every tenant-scoped table so the database
enforces isolation independently of application code (plan §1.2). Policies compare the
row's ``tenant_id`` to the ``app.current_tenant`` session var set per request by
TenantContextMiddleware.

The operation is **vendor-aware**: on PostgreSQL it installs the RLS policy; on any other
backend (e.g. SQLite used for fast local/CI unit tests) it is a no-op so migrations still
apply. RLS is a production-Postgres guarantee, verified by a Postgres-only test in the
tenant-isolation harness.

Example migration operation:

    from core.rls import enable_rls
    operations = [enable_rls("clinical_data_observation")]
"""
from __future__ import annotations

from django.db import migrations


def _forward_sql(table: str, tenant_column: str) -> str:
    return f"""
        ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;
        ALTER TABLE {table} FORCE ROW LEVEL SECURITY;
        DROP POLICY IF EXISTS tenant_isolation ON {table};
        CREATE POLICY tenant_isolation ON {table}
            USING ({tenant_column}::text = current_setting('app.current_tenant', true))
            WITH CHECK ({tenant_column}::text = current_setting('app.current_tenant', true));
    """


def _reverse_sql(table: str) -> str:
    return f"""
        DROP POLICY IF EXISTS tenant_isolation ON {table};
        ALTER TABLE {table} DISABLE ROW LEVEL SECURITY;
    """


def enable_rls(table: str, tenant_column: str = "tenant_id") -> migrations.RunPython:
    """Return a migration operation that installs the RLS policy on PostgreSQL only."""

    def forward(apps, schema_editor):
        if schema_editor.connection.vendor != "postgresql":
            return
        schema_editor.execute(_forward_sql(table, tenant_column))

    def reverse(apps, schema_editor):
        if schema_editor.connection.vendor != "postgresql":
            return
        schema_editor.execute(_reverse_sql(table))

    return migrations.RunPython(forward, reverse)
