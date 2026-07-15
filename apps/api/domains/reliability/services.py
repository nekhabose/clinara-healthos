"""Reliability service interface (spec §12.4, §11.4, §7.4).

Wires the pure SLO evaluator and provider-failover selector to persistence and events:

  * ``evaluate_and_record`` — evaluate the spec §12.4 objective set for a window, persist any
    breach, and publish an ``SLOBreached`` event so alerting reacts. Returns the full report
    for the ops SLO dashboard and the release gate.
  * ``choose_provider`` — thin pass-through to the failover selector, loading the live kill
    switch set so a killed provider is skipped.
"""
from __future__ import annotations

from clinara_shared_types import EventType
from django.db import transaction

from core.outbox import publish_event
from domains.audit import services as audit
from domains.killswitch.services import _load_active

from .core import ProviderSelection, SLOReport, evaluate_slos, select_provider
from .models import SLOBreachRecord


@transaction.atomic
def evaluate_and_record(observed: dict[str, float], *, window_label: str = "") -> SLOReport:
    """Evaluate SLOs, persist + announce each breach. Idempotent per (key, window)."""
    report = evaluate_slos(observed)
    for breach in report.breaches:
        record, created = SLOBreachRecord.objects.get_or_create(
            slo_key=breach.key,
            window_label=window_label,
            defaults={
                "description": breach.description,
                "observed": breach.observed,
                "target": breach.target,
            },
        )
        if not created:
            continue
        audit.record(
            actor="system",
            action="slo.breach",
            resource=f"slo:{breach.key}",
            reason=f"observed={breach.observed} target={breach.target}",
        )
        publish_event(
            event_type=EventType.SLO_BREACHED.value,
            idempotency_key=f"slo-breach-{record.id}",
            payload={
                "slo_key": breach.key,
                "observed": breach.observed,
                "target": breach.target,
                "window": window_label,
            },
        )
    return report


def choose_provider(preference: list[str], health: dict[str, bool]) -> ProviderSelection:
    """Pick a healthy, un-killed LLM provider (or None → fall back to the no-LLM path)."""
    return select_provider(preference, health, _load_active())


__all__ = ["evaluate_and_record", "choose_provider", "evaluate_slos"]
