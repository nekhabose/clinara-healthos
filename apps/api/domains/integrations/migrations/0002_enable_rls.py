"""Enable RLS for tenant isolation (plan §1.2). No-op off PostgreSQL."""
from django.db import migrations

from core.rls import enable_rls


class Migration(migrations.Migration):
    dependencies = [("integrations", "0001_initial")]
    operations = [enable_rls("integrations_inboundmessage")]
