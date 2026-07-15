#!/usr/bin/env python
"""Release-gate CLI (GA hardening — spec §13.5).

Collects the release signals from the environment (populated by upstream CI jobs and release
metadata) and evaluates the universal §13.5 gate. Exits non-zero — failing the build — if any
condition is unmet, so a release physically cannot proceed through CI while blocked.

Each signal is read from an environment variable that must be the literal string "true" to
count as satisfied; anything else (including unset) is treated as failing, matching the
fail-closed contract of ``core.release_gate``.

    GATE_CRITICAL_REGRESSION=true GATE_SAFETY_RULES=true ... python scripts/release_gate.py

Wire this as the final, required job in the deploy workflow, depending on every test/approval
job, so green upstream jobs export their result into these variables.
"""
from __future__ import annotations

import os
import sys

# Allow running as a plain script (python scripts/release_gate.py) from apps/api.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.release_gate import GateSignals, evaluate  # noqa: E402

# Map each spec §13.5 condition to the env var an upstream job sets.
_ENV = {
    "critical_regression_passed": "GATE_CRITICAL_REGRESSION",
    "safety_rules_passed": "GATE_SAFETY_RULES",
    "mapping_validation_passed": "GATE_MAPPING_VALIDATION",
    "cross_tenant_isolation_passed": "GATE_CROSS_TENANT_ISOLATION",
    "clinical_approval_present": "GATE_CLINICAL_APPROVAL",
    "historical_high_risk_stable": "GATE_HISTORICAL_HIGH_RISK",
    "observability_complete": "GATE_OBSERVABILITY",
    "rollback_available": "GATE_ROLLBACK",
}


def _flag(var: str) -> bool:
    return os.environ.get(var, "").strip().lower() == "true"


def main() -> int:
    signals = GateSignals(**{attr: _flag(var) for attr, var in _ENV.items()})
    result = evaluate(signals)
    if result.allowed:
        print("✅ Release gate PASSED — all spec §13.5 conditions satisfied.")
        return 0
    print("⛔ Release gate BLOCKED — unmet §13.5 conditions:")
    for condition in result.failed_conditions:
        print(f"  - {condition}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
