"""Release-gate core (GA hardening — spec §13.5).

Django-free; runs with PYTHONPATH=apps/api. The gate is fail-closed: every condition must be
proven satisfied for a release to proceed.
"""
from core import release_gate


def _all_green():
    return release_gate.GateSignals(
        critical_regression_passed=True,
        safety_rules_passed=True,
        mapping_validation_passed=True,
        cross_tenant_isolation_passed=True,
        clinical_approval_present=True,
        historical_high_risk_stable=True,
        observability_complete=True,
        rollback_available=True,
    )


def test_all_green_allows_release():
    result = release_gate.evaluate(_all_green())
    assert result.allowed is True
    assert result.failed_conditions == ()


def test_default_signals_block_release():
    # Every signal defaults to failing, so an un-populated GateSignals blocks — fail-closed.
    result = release_gate.evaluate(release_gate.GateSignals())
    assert result.blocked is True
    assert len(result.failed_conditions) == 8


def test_cross_tenant_failure_blocks_and_is_named():
    signals = _all_green()
    signals = release_gate.GateSignals(
        **{**signals.__dict__, "cross_tenant_isolation_passed": False}
    )
    result = release_gate.evaluate(signals)
    assert result.blocked is True
    assert any("isolation" in c.lower() for c in result.failed_conditions)


def test_missing_rollback_blocks():
    signals = release_gate.GateSignals(**{**_all_green().__dict__, "rollback_available": False})
    result = release_gate.evaluate(signals)
    assert result.blocked is True
    assert any("rollback" in c.lower() for c in result.failed_conditions)


def test_all_eight_spec_conditions_present():
    # Guard against silently dropping a §13.5 condition.
    result = release_gate.evaluate(release_gate.GateSignals())
    assert len(release_gate._CONDITIONS) == 8
    assert len(result.failed_conditions) == 8
