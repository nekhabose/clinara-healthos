"""Enable RLS for the Phase 3 gateway tables (plan §1.2). No-op off PostgreSQL."""
from django.db import migrations

from core.rls import enable_rls


class Migration(migrations.Migration):
    dependencies = [
        ("integrations", "0003_inboundmessage_sequence_alter_inboundmessage_status_and_more")
    ]
    operations = [
        enable_rls("integrations_integration"),
        enable_rls("integrations_integrationendpoint"),
        enable_rls("integrations_integrationcredential"),
        enable_rls("integrations_ratelimitstate"),
        enable_rls("integrations_deadletterevent"),
        enable_rls("integrations_integrationerror"),
        enable_rls("integrations_alert"),
        enable_rls("integrations_incident"),
    ]
