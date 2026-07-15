"""Enable RLS for tenant isolation (plan §1.2). No-op off PostgreSQL."""
from django.db import migrations

from core.rls import enable_rls


class Migration(migrations.Migration):
    dependencies = [("refills", "0001_initial")]
    operations = [
        enable_rls("refills_medicationstatement"),
        enable_rls("refills_allergyintolerance"),
        enable_rls("refills_clientmonitoringpolicy"),
        enable_rls("refills_refillworkflow"),
        enable_rls("refills_refillevaluationrecord"),
        enable_rls("refills_refillreview"),
    ]
