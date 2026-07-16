"""Public service interface for the Identity module (spec §7.4, §10.2)."""
from __future__ import annotations

from datetime import timedelta

from clinara_shared_types import EventType
from django.db import transaction
from django.utils import timezone

from core.outbox import publish_event
from domains.audit import services as audit

from . import breakglass
from .models import BreakGlassGrantRecord, User
from .roles import PHI_ACCESS_ROLES


def can_access_phi(user: User) -> bool:
    """Whether a user's role permits PHI access (drives PHI-access audit + authorization)."""
    return user.role in PHI_ACCESS_ROLES


# ---- Break-glass emergency access (spec §10.2) ----

def grant_break_glass(*, responder: str, reason: str, ttl_seconds: int) -> BreakGlassGrantRecord:
    """Validate + persist a time-boxed emergency-access grant. Always audited.

    Raises ``ValueError`` if the request violates a break-glass invariant (missing reason,
    non-positive or over-cap TTL). A denial is recorded in its OWN committed transaction so
    the refusal survives in the audit trail even though the request fails (a rollback of the
    grant path must not erase the record that someone attempted break-glass access).
    """
    decision = breakglass.request_grant(responder, reason, ttl_seconds)
    if not decision.granted:
        audit.record(
            actor=responder,
            action="breakglass.denied",
            resource="breakglass",
            reason=decision.reason,
        )
        raise ValueError(decision.reason)

    with transaction.atomic():
        now = timezone.now()
        record = BreakGlassGrantRecord.objects.create(
            responder=responder,
            reason=reason,
            expires_at=now + timedelta(seconds=ttl_seconds),
        )
        audit.record(
            actor=responder,
            action="breakglass.grant",
            resource=f"breakglass:{record.id}",
            reason=reason,
            after_state={"expires_at": record.expires_at.isoformat()},
        )
        publish_event(
            event_type=EventType.BREAK_GLASS_GRANTED.value,
            idempotency_key=f"breakglass-grant-{record.id}",
            payload={"responder": responder, "expires_at": record.expires_at.isoformat()},
        )
    return record


@transaction.atomic
def revoke_break_glass(*, grant_id: str, revoked_by: str) -> None:
    """Revoke an active grant early. Audited + event-published."""
    record = BreakGlassGrantRecord.objects.get(id=grant_id)
    if record.revoked:
        return
    record.revoked = True
    record.revoked_by = revoked_by
    record.revoked_at = timezone.now()
    record.save(update_fields=["revoked", "revoked_by", "revoked_at"])
    audit.record(
        actor=revoked_by,
        action="breakglass.revoke",
        resource=f"breakglass:{record.id}",
        before_state={"revoked": False},
        after_state={"revoked": True},
    )
    publish_event(
        event_type=EventType.BREAK_GLASS_REVOKED.value,
        idempotency_key=f"breakglass-revoke-{record.id}",
        payload={"responder": record.responder, "revoked_by": revoked_by},
    )


def break_glass_active(record: BreakGlassGrantRecord) -> bool:
    """Is this grant currently valid? Fail-closed on revoke/expiry."""
    if record.revoked:
        return False
    return timezone.now() <= record.expires_at
