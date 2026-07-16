"""Enable RLS for tenant isolation (plan §1.2). No-op off PostgreSQL."""
from django.db import migrations

from core.rls import enable_rls


class Migration(migrations.Migration):
    dependencies = [("workflows", "0001_initial")]
    operations = [
        enable_rls("workflows_workflowinstance"),
        enable_rls("workflows_protocolevaluationrecord"),
        enable_rls("workflows_generatedcommunication"),
        enable_rls("workflows_humanreview"),
        enable_rls("workflows_escalation"),
    ]
