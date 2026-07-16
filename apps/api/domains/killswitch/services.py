"""Kill-switch service interface (spec §11.4, §7.4).

Wires the pure resolver (``killswitch.core``) to persistence, audit, and the outbox. Two
responsibilities:

  * **Operate** switches — ``engage`` / ``release`` — each fully audited and event-published.
  * **Consult** switches — ``check`` / ``automation_allowed`` — the read path every automation
    decision calls before acting. Loading the active set on each check keeps the answer
    current the instant an operator pulls a switch.

Engaging/releasing is a platform-operator action (not tenant-scoped RLS data), so these are
gated by the caller's RBAC, not by the tenant session var.
"""
from __future__ import annotations

from clinara_shared_types import EventType, KillSwitchScope
from django.db import transaction
from django.utils import timezone

from core.outbox import publish_event
from domains.audit import services as audit

from .core import AutomationAttempt, KillSwitch, KillSwitchDecision, resolve
from .models import KillSwitchRecord


def _load_active() -> list[KillSwitch]:
    return [
        KillSwitch(
            scope=KillSwitchScope(r.scope),
            target=r.target,
            reason=r.reason,
            engaged_by=r.engaged_by,
        )
        for r in KillSwitchRecord.objects.filter(active=True)
    ]


@transaction.atomic
def engage(*, scope: str, target: str = "*", reason: str, engaged_by: str) -> KillSwitchRecord:
    """Engage (or idempotently re-affirm) a kill switch. Audited + event-published."""
    scope_value = KillSwitchScope(scope).value
    record, created = KillSwitchRecord.objects.get_or_create(
        scope=scope_value,
        target=target,
        active=True,
        defaults={"reason": reason, "engaged_by": engaged_by},
    )
    audit.record(
        actor=engaged_by,
        action="killswitch.engage",
        resource=f"killswitch:{scope_value}:{target}",
        reason=reason,
        after_state={"active": True},
    )
    publish_event(
        event_type=EventType.KILL_SWITCH_ENGAGED.value,
        idempotency_key=f"killswitch-engage-{record.id}",
        payload={"scope": scope_value, "target": target, "engaged_by": engaged_by},
    )
    return record


@transaction.atomic
def release(*, scope: str, target: str = "*", released_by: str, reason: str = "") -> int:
    """Release active switches matching (scope, target). Returns the number released."""
    scope_value = KillSwitchScope(scope).value
    qs = KillSwitchRecord.objects.filter(active=True, scope=scope_value, target=target)
    count = 0
    for record in qs:
        record.active = False
        record.released_by = released_by
        record.released_at = timezone.now()
        record.save(update_fields=["active", "released_by", "released_at"])
        audit.record(
            actor=released_by,
            action="killswitch.release",
            resource=f"killswitch:{scope_value}:{target}",
            reason=reason,
            before_state={"active": True},
            after_state={"active": False},
        )
        publish_event(
            event_type=EventType.KILL_SWITCH_RELEASED.value,
            idempotency_key=f"killswitch-release-{record.id}",
            payload={"scope": scope_value, "target": target, "released_by": released_by},
        )
        count += 1
    return count


def check(attempt: AutomationAttempt) -> KillSwitchDecision:
    """Resolve ``attempt`` against the current active switch set (the read path)."""
    return resolve(attempt, _load_active())


def automation_allowed(attempt: AutomationAttempt) -> bool:
    """True iff no active kill switch suppresses this automation attempt."""
    return check(attempt).allowed


__all__ = ["engage", "release", "check", "automation_allowed", "AutomationAttempt"]
