"""Scheduled retention/purge task (plan Phase 11 — closes G7).

Runs on a Celery beat (see ``clinara.celery``): once per period it sweeps every active,
non-terminated tenant's expired PHI per that tenant's retention policy. Idempotent and safe to
re-run — a second pass in the same window purges nothing new. Autodiscovered because the app is
in ``INSTALLED_APPS`` and this module is named ``tasks``.
"""
from __future__ import annotations

import logging

from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task(name="domains.retention.tasks.run_scheduled_purge_all")
def run_scheduled_purge_all() -> int:
    """Purge expired PHI for all tenants. Returns the total number of rows purged."""
    from . import services

    total = services.purge_all_tenants()
    logger.info("retention_scheduled_purge_complete", extra={"total_purged": total})
    return total
