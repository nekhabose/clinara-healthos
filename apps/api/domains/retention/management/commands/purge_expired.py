"""Manual/cron entry point for the retention purge (plan Phase 11 — closes G7).

    python manage.py purge_expired               # sweep every active tenant
    python manage.py purge_expired --tenant <id> # one tenant
    python manage.py purge_expired --dry-run      # report counts, delete nothing

The scheduled path is the Celery beat task ``domains.retention.tasks.run_scheduled_purge_all``;
this command is for ops/backfill and mirrors it. It sets the tenant + correlation context itself
(like ``seed_demo``) because it runs outside the request middleware that normally binds RLS.
"""
from __future__ import annotations

from django.core.management.base import BaseCommand

from domains.retention import services


class Command(BaseCommand):
    help = "Purge PHI past each tenant's retention window (minimal-necessary minimization)."

    def add_arguments(self, parser) -> None:
        parser.add_argument("--tenant", dest="tenant", default=None,
                            help="Purge a single tenant id (default: all active tenants).")
        parser.add_argument("--dry-run", dest="dry_run", action="store_true",
                            help="Report what would be purged without deleting anything.")

    def handle(self, *args, **options) -> None:
        tenant = options["tenant"]
        dry_run = options["dry_run"]
        if tenant:
            run = services.run_scheduled_purge(tenant_id=tenant, dry_run=dry_run)
            verb = "would purge" if dry_run else "purged"
            self.stdout.write(
                f"tenant {tenant}: {verb} {run.total_purged} rows "
                f"(certificate {run.certificate_hash[:12]})"
            )
            return
        if dry_run:
            self.stderr.write("--dry-run requires --tenant (all-tenant dry run is not supported)")
            return
        total = services.purge_all_tenants()
        self.stdout.write(f"purged {total} rows across all active tenants")
