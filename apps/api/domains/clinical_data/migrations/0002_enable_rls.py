"""Enable PostgreSQL Row-Level Security for tenant isolation (plan §1.2).

No-op on non-PostgreSQL backends (see core.rls) so migrations apply on SQLite test DBs.
"""
from django.db import migrations

from core.rls import enable_rls


class Migration(migrations.Migration):
    dependencies = [("clinical_data", "0001_initial")]
    operations = [
        enable_rls("clinical_data_patientreference"),
        enable_rls("clinical_data_observation"),
    ]
