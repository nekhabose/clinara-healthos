"""Deterministic token-bucket rate limiter + silent-gap detector (plan Phase 3).

Both are pure so they are unit-testable without a clock or a broker. The gateway supplies
``now`` explicitly (never reads the clock inside), which keeps rate decisions and gap
alerts reproducible and replayable.

  * ``TokenBucket`` — guard an abusive source (spec §6.7.4 "rate-limit abusive sources").
  * ``detect_silent_gap`` — detect the *absence* of expected traffic (plan Phase 3 key
    decision), not just failures of received traffic.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class TokenBucket:
    """A classic token bucket. ``capacity`` tokens, refilled ``refill_per_second``.

    State (``tokens``, ``last_refill``) is serialisable so it can live in a DB row per
    (tenant, source) and survive across requests. ``allow(now, cost)`` mutates state and
    returns whether the request is permitted.
    """

    capacity: float
    refill_per_second: float
    tokens: float | None = None   # None → start full; 0.0 is a *legitimately empty* bucket
    last_refill: float = 0.0

    def __post_init__(self) -> None:
        if self.tokens is None:
            self.tokens = self.capacity

    def allow(self, now: float, cost: float = 1.0) -> bool:
        elapsed = max(0.0, now - self.last_refill)
        self.tokens = min(self.capacity, self.tokens + elapsed * self.refill_per_second)
        self.last_refill = now
        if self.tokens >= cost:
            self.tokens -= cost
            return True
        return False


def detect_silent_gap(
    *, last_seen_epoch: float | None, now_epoch: float, expected_interval_seconds: int,
    grace_multiplier: float = 2.0,
) -> bool:
    """True when an interface has gone silent longer than it should have.

    An interface that emits roughly every ``expected_interval_seconds`` is *expected* to be
    heard from within ``grace_multiplier ×`` that window. Exceeding it means expected traffic
    has silently stopped — a distinct failure mode from received-but-errored traffic. A
    never-seen interface (``last_seen_epoch is None``) is not yet a gap.
    """
    if expected_interval_seconds <= 0 or last_seen_epoch is None:
        return False
    return (now_epoch - last_seen_epoch) > expected_interval_seconds * grace_multiplier


__all__ = ["TokenBucket", "detect_silent_gap"]
