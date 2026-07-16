"""Enable RLS for tenant isolation (plan §1.2). No-op off PostgreSQL."""
from django.db import migrations

from core.rls import enable_rls


class Migration(migrations.Migration):
    dependencies = [("feedback", "0001_initial")]
    operations = [
        enable_rls("feedback_clinicianfeedback"),
        enable_rls("feedback_patientresponse"),
        enable_rls("feedback_protocolfeedback"),
    ]
