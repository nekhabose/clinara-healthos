"""Celery application. Workers (apps/workers) run against this same codebase."""
import os

from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "clinara.settings.local")

app = Celery("clinara")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()

# The outbox relay runs on a short beat so committed domain events reach the bus
# promptly (spec §7.5 — no silent loss).
app.conf.beat_schedule = {
    "relay-domain-event-outbox": {
        "task": "core.tasks.relay_outbox",
        "schedule": 5.0,
    }
}
