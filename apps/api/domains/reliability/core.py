"""Service-Level Objective evaluation + LLM provider failover (GA hardening — spec §12.4).

Two pure, Django-free concerns that gate general availability:

1. **SLO evaluation.** The spec §12.4 SLO set is encoded as declarative targets. Given a
   window of observed metrics, ``evaluate_slos`` reports, per objective, the observed value,
   the target, and whether it is met — the input to the release gate's "observability
   complete / SLOs met" condition (spec §13.5) and to the ops SLO dashboard. No hidden
   rounding that could flatter a near-miss: comparisons are exact against the target.

2. **Provider failover.** ``select_provider`` walks an ordered preference list and returns
   the first provider that is healthy AND not under a kill switch (spec §11.4). This is how
   "provider failover" and "LLM kill-switch validation across all scopes" become real: the
   generation/classification layer asks this module which provider to use, and a killed or
   unhealthy provider is transparently skipped — never silently used.

Both are deterministic and side-effect free so they can be exhaustively unit-tested and
replayed in the decision trace.
"""
from __future__ import annotations

from dataclasses import dataclass

from domains.killswitch.core import KillSwitch, llm_provider_suppressed

# ---- SLO evaluation (spec §12.4) -------------------------------------------------------

@dataclass(frozen=True)
class SLOTarget:
    """One objective. ``higher_is_better`` picks the comparison direction.

    ``max_value`` bounds latency-style objectives ("99% of critical events within 30s"): the
    observed value is the fraction meeting the bound, compared with ``>=`` to ``target``.
    """

    key: str
    description: str
    target: float
    higher_is_better: bool = True


# The full spec §12.4 objective set. Values are fractions in [0, 1] except where noted.
SLO_TARGETS: tuple[SLOTarget, ...] = (
    SLOTarget("ingestion_availability", "Ingestion availability", 0.999),
    SLOTarget("routine_within_2min", "Routine events processed within 2 minutes", 0.99),
    SLOTarget("critical_within_30s", "Critical events processed within 30 seconds", 0.99),
    SLOTarget("silent_message_loss", "Zero silent message loss", 0.0, higher_is_better=False),
    SLOTarget("audit_recording_success", "Successful audit recording", 0.999),
    SLOTarget("approved_channel_delivery", "Successful approved-channel delivery", 0.99),
    SLOTarget("decision_trace_availability", "Decision-trace availability (completed)", 1.0),
)


@dataclass(frozen=True)
class SLOResult:
    key: str
    description: str
    observed: float
    target: float
    met: bool


@dataclass(frozen=True)
class SLOReport:
    results: tuple[SLOResult, ...]

    @property
    def all_met(self) -> bool:
        return all(r.met for r in self.results)

    @property
    def breaches(self) -> tuple[SLOResult, ...]:
        return tuple(r for r in self.results if not r.met)


def _is_met(target: SLOTarget, observed: float) -> bool:
    if target.higher_is_better:
        return observed >= target.target
    return observed <= target.target


def evaluate_slos(observed: dict[str, float]) -> SLOReport:
    """Evaluate every spec §12.4 objective against ``observed`` metric values.

    A missing metric is a breach, not a pass: unobservable objectives fail the release gate's
    "observability complete" condition rather than being silently assumed healthy.
    """
    results: list[SLOResult] = []
    for target in SLO_TARGETS:
        if target.key not in observed:
            results.append(
                SLOResult(target.key, target.description, float("nan"), target.target, met=False)
            )
            continue
        value = observed[target.key]
        results.append(
            SLOResult(target.key, target.description, value, target.target, _is_met(target, value))
        )
    return SLOReport(tuple(results))


# ---- LLM provider failover (spec §11.4 provider scope) ---------------------------------

@dataclass(frozen=True)
class ProviderSelection:
    provider: str | None
    skipped: tuple[tuple[str, str], ...]  # (provider, reason) for each one passed over

    @property
    def available(self) -> bool:
        return self.provider is not None


def select_provider(
    preference: list[str],
    health: dict[str, bool],
    switches: list[KillSwitch] | None = None,
) -> ProviderSelection:
    """Pick the first provider that is healthy and not killed, honoring ``preference`` order.

    Returns ``provider=None`` when every candidate is unhealthy or killed — the caller must
    then fall back to the deterministic/no-LLM path (never proceed without a provider). Each
    skipped provider is recorded with the reason so failover is fully explainable.
    """
    switches = switches or []
    skipped: list[tuple[str, str]] = []
    for name in preference:
        if llm_provider_suppressed(name, switches):
            skipped.append((name, "kill_switch"))
            continue
        if not health.get(name, False):
            skipped.append((name, "unhealthy"))
            continue
        return ProviderSelection(provider=name, skipped=tuple(skipped))
    return ProviderSelection(provider=None, skipped=tuple(skipped))
