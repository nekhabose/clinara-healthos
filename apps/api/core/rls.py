"""Row-Level Security helpers.

Use ``enable_rls`` inside a data migration for every tenant-scoped table so the database
enforces isolation independently of application code (plan §1.2). Policies compare the
row's ``tenant_id`` to the ``app.current_tenant`` session var set per request by
TenantContextMiddleware.

Example migration operation:

    from core.rls import enable_rls
    operations = [enable_rls("clinical_data_observation")]
"""
from __future__ import annotations

from django.db import migrations


def enable_rls(table: str, tenant_column: str = "tenant_id") -> migrations.RunSQL:
    forward = f"""
        ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;
        ALTER TABLE {table} FORCE ROW LEVEL SECURITY;
        DROP POLICY IF EXISTS tenant_isolation ON {table};
        CREATE POLICY tenant_isolation ON {table}
            USING ({tenant_column}::text = current_setting('app.current_tenant', true))
            WITH CHECK ({tenant_column}::text = current_setting('app.current_tenant', true));
    """
    reverse = f"""
        DROP POLICY IF EXISTS tenant_isolation ON {table};
        ALTER TABLE {table} DISABLE ROW LEVEL SECURITY;
    """
    return migrations.RunSQL(sql=forward, reverse_sql=reverse)
