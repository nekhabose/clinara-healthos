"""Deterministic retry/backoff policy for outbound write-back (plan Phase 7).

Pure and clock-free like the rest of the SDK primitives: the policy computes *how many*
attempts and *how long* to wait, but never sleeps and never reads the clock. The caller
(the delivery service) owns the loop and injects a sleeper, so retries are reproducible in
tests and the backoff schedule can be unit-asserted.

Only *retryable* failures (transient 5xx / 429 / network) consume attempts; a terminal 4xx
fails immediately — retrying a rejected request would just re-reject it and delay the
operator alert.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int = 3
    base_delay_seconds: float = 0.5
    max_delay_seconds: float = 8.0
    multiplier: float = 2.0

    def __post_init__(self) -> None:
        if self.max_attempts < 1:
            raise ValueError("max_attempts must be >= 1")

    def backoff(self, attempt: int) -> float:
        """Delay *before* ``attempt`` (1-indexed). Attempt 1 is immediate (0.0);
        subsequent attempts back off exponentially, capped at ``max_delay_seconds``."""
        if attempt <= 1:
            return 0.0
        delay = self.base_delay_seconds * (self.multiplier ** (attempt - 2))
        return min(delay, self.max_delay_seconds)

    def should_retry(self, attempt: int, *, retryable: bool) -> bool:
        """Retry only when the error is retryable and attempts remain."""
        return retryable and attempt < self.max_attempts


NO_RETRY = RetryPolicy(max_attempts=1)

__all__ = ["RetryPolicy", "NO_RETRY"]
