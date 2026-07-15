"""Break-glass emergency access (GA hardening — spec §10.2).

Break-glass grants a responder time-boxed elevated access during an incident, with a
mandatory reason and a hard expiry. This is the pure, Django-free decision core: it never
touches the DB or the clock. The caller passes ``now`` (and the grant window) so the
decision is deterministic and unit-testable; the Django/service layer supplies the real
clock, persists the grant, and — critically — emits an audit record on both grant and use
(break-glass access is always audited, spec §10.2 / §10.4).

Invariants:
  * **A reason is mandatory.** No reason → no grant.
  * **Time-boxed.** Access is valid only within [granted_at, granted_at + ttl]; there is no
    "permanent" break-glass. An expired or revoked grant denies.
  * **Bounded TTL.** A grant longer than ``MAX_TTL_SECONDS`` is refused, so a fat-fingered
    window cannot leave standing elevated access.
"""
from __future__ import annotations

from dataclasses import dataclass

MAX_TTL_SECONDS = 60 * 60  # 1 hour hard cap on any single break-glass grant.


@dataclass(frozen=True)
class BreakGlassGrant:
    """An emergency-access grant. Times are epoch seconds so the core stays clock-free."""

    responder: str
    reason: str
    granted_at: float
    ttl_seconds: float
    revoked: bool = False


@dataclass(frozen=True)
class GrantDecision:
    granted: bool
    reason: str = ""


def request_grant(responder: str, reason: str, ttl_seconds: float) -> GrantDecision:
    """Validate a break-glass request before it is persisted.

    Enforces the mandatory-reason and bounded-TTL invariants. Returns a decision the service
    layer turns into a persisted, audited grant (or a logged denial).
    """
    if not reason or not reason.strip():
        return GrantDecision(granted=False, reason="break-glass requires a documented reason")
    if ttl_seconds <= 0:
        return GrantDecision(granted=False, reason="ttl must be positive")
    if ttl_seconds > MAX_TTL_SECONDS:
        return GrantDecision(
            granted=False, reason=f"ttl exceeds the {MAX_TTL_SECONDS}s break-glass cap"
        )
    if not responder or not responder.strip():
        return GrantDecision(granted=False, reason="a responder identity is required")
    return GrantDecision(granted=True)


def is_active(grant: BreakGlassGrant, now: float) -> bool:
    """Is ``grant`` currently valid at time ``now`` (epoch seconds)?

    Fail-closed: revoked or outside the window ⇒ inactive. Callers gate elevated access on
    this and must audit every access made under an active grant.
    """
    if grant.revoked:
        return False
    if now < grant.granted_at:
        return False
    return now <= grant.granted_at + grant.ttl_seconds
