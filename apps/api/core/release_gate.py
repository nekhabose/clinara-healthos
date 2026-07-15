"""Release-gate evaluation (GA hardening — spec §13.5).

The universal release gate: a release CANNOT proceed if any of the spec §13.5 conditions is
unmet. This is the pure, Django-free decision core — a set of observed signals in, an
allow/block verdict with the exact failing conditions out. The CI job (``scripts/
release_gate.py``) collects the signals and calls ``evaluate``; a block fails the build.

The gate is deliberately fail-closed: every condition must be *proven* satisfied. A missing
signal is treated as unmet, never assumed green — you cannot ship because a check "didn't
report a problem"; it has to report success.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class GateSignals:
    """Observed release signals. Each maps to a spec §13.5 blocking condition.

    All default to the failing value so an un-supplied signal blocks the release rather than
    silently passing it.
    """

    critical_regression_passed: bool = False
    safety_rules_passed: bool = False
    mapping_validation_passed: bool = False
    cross_tenant_isolation_passed: bool = False
    clinical_approval_present: bool = False
    historical_high_risk_stable: bool = False
    observability_complete: bool = False
    rollback_available: bool = False


# (attribute, human description) for each spec §13.5 condition, in spec order.
_CONDITIONS: tuple[tuple[str, str], ...] = (
    ("critical_regression_passed", "Critical regression tests pass"),
    ("safety_rules_passed", "Safety rules pass"),
    ("mapping_validation_passed", "Mapping validation passes"),
    ("cross_tenant_isolation_passed", "Cross-tenant isolation tests pass"),
    ("clinical_approval_present", "Required clinical approval present"),
    ("historical_high_risk_stable", "Historical high-risk cases unchanged"),
    ("observability_complete", "Observability complete"),
    ("rollback_available", "Rollback available"),
)


@dataclass(frozen=True)
class GateResult:
    allowed: bool
    failed_conditions: tuple[str, ...] = field(default_factory=tuple)

    @property
    def blocked(self) -> bool:
        return not self.allowed


def evaluate(signals: GateSignals) -> GateResult:
    """Return whether the release may proceed, and every failing condition if not.

    Deterministic and total: a release is allowed only when all eight §13.5 conditions hold.
    """
    failed = tuple(desc for attr, desc in _CONDITIONS if not getattr(signals, attr))
    return GateResult(allowed=not failed, failed_conditions=failed)
