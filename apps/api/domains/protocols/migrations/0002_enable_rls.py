"""Enable RLS for tenant isolation (plan §1.2). No-op off PostgreSQL."""
from django.db import migrations

from core.rls import enable_rls


class Migration(migrations.Migration):
    dependencies = [("protocols", "0001_initial")]
    operations = [
        enable_rls("protocols_protocol"),
        enable_rls("protocols_protocolversion"),
        enable_rls("protocols_ruletestcase"),
        enable_rls("protocols_simulationrun"),
        enable_rls("protocols_deployment"),
        enable_rls("protocols_rollback"),
    ]
