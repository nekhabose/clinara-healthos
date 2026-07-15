"""Outbox relay task.

Publishes PENDING outbox rows to the durable event bus (SQS/EventBridge in AWS; a local
stub in dev) and marks them PUBLISHED. Runs on a Celery beat (see clinara.celery).

Idempotent and safe to re-run: rows are claimed with select_for_update(skip_locked) so
multiple relay workers don't double-publish.
"""
from __future__ import annotations

import logging

from celery import shared_task
from django.db import transaction
from django.utils import timezone

from .models import DomainEventOutbox, OutboxStatus

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 8
BATCH_SIZE = 100


@shared_task(name="core.tasks.relay_outbox")
def relay_outbox() -> int:
    """Publish a batch of pending events. Returns the number published."""
    published = 0
    with transaction.atomic():
        rows = (
            DomainEventOutbox.objects.select_for_update(skip_locked=True)
            .filter(status=OutboxStatus.PENDING)
            .order_by("created_at")[:BATCH_SIZE]
        )
        for event in rows:
            try:
                _publish_to_bus(event)
                event.status = OutboxStatus.PUBLISHED
                event.published_at = timezone.now()
                published += 1
            except Exception as exc:  # noqa: BLE001 — capture, never drop
                event.attempts += 1
                event.last_error = str(exc)[:2000]
                event.status = (
                    OutboxStatus.DEAD_LETTER
                    if event.attempts >= MAX_ATTEMPTS
                    else OutboxStatus.PENDING
                )
                logger.warning("outbox_publish_failed", extra={"event_type": event.event_type})
            event.save(update_fields=["status", "published_at", "attempts", "last_error"])
    return published


def _publish_to_bus(event: DomainEventOutbox) -> None:
    """Publish one event to the bus. Replaced with a boto3 EventBridge/SQS client in infra."""
    # Phase 0 stub: real publisher wired in Phase 3. Kept intentionally minimal.
    logger.info("domain_event_published", extra={"event_type": event.event_type})
