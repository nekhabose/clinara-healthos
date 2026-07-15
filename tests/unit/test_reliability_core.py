"""SLO evaluation + provider failover core (GA hardening — spec §12.4, §11.4).

Django-free; runs with PYTHONPATH=apps/api.
"""
import math

from clinara_shared_types import KillSwitchScope

from domains.killswitch.core import KillSwitch
from domains.reliability import core


# ---- SLO evaluation ----

def _all_met_metrics():
    return {
        "ingestion_availability": 0.9995,
        "routine_within_2min": 0.995,
        "critical_within_30s": 0.995,
        "silent_message_loss": 0.0,
        "audit_recording_success": 0.9999,
        "approved_channel_delivery": 0.995,
        "decision_trace_availability": 1.0,
    }


def test_all_slos_met():
    report = core.evaluate_slos(_all_met_metrics())
    assert report.all_met is True
    assert report.breaches == ()


def test_every_spec_objective_is_covered():
    keys = {r.key for r in core.evaluate_slos(_all_met_metrics()).results}
    assert keys == {t.key for t in core.SLO_TARGETS}
    assert len(keys) == 7


def test_availability_below_target_breaches():
    m = _all_met_metrics()
    m["ingestion_availability"] = 0.998  # below 0.999
    report = core.evaluate_slos(m)
    assert report.all_met is False
    assert any(b.key == "ingestion_availability" for b in report.breaches)


def test_silent_message_loss_is_lower_is_better():
    m = _all_met_metrics()
    m["silent_message_loss"] = 0.0001  # any loss breaches the zero target
    report = core.evaluate_slos(m)
    assert any(b.key == "silent_message_loss" for b in report.breaches)


def test_decision_trace_must_be_100_percent():
    m = _all_met_metrics()
    m["decision_trace_availability"] = 0.999
    report = core.evaluate_slos(m)
    assert any(b.key == "decision_trace_availability" for b in report.breaches)


def test_missing_metric_is_a_breach_not_a_pass():
    m = _all_met_metrics()
    del m["audit_recording_success"]
    report = core.evaluate_slos(m)
    assert report.all_met is False
    breach = next(b for b in report.breaches if b.key == "audit_recording_success")
    assert math.isnan(breach.observed)


# ---- Provider failover ----

def test_selects_first_healthy_unkilled_provider():
    sel = core.select_provider(
        ["anthropic", "openai"], {"anthropic": True, "openai": True}, []
    )
    assert sel.provider == "anthropic"
    assert sel.skipped == ()


def test_skips_unhealthy_provider():
    sel = core.select_provider(
        ["anthropic", "openai"], {"anthropic": False, "openai": True}, []
    )
    assert sel.provider == "openai"
    assert sel.skipped == (("anthropic", "unhealthy"),)


def test_skips_killed_provider_even_if_healthy():
    switches = [KillSwitch(KillSwitchScope.MODEL_PROVIDER, target="anthropic")]
    sel = core.select_provider(
        ["anthropic", "openai"], {"anthropic": True, "openai": True}, switches
    )
    assert sel.provider == "openai"
    assert sel.skipped == (("anthropic", "kill_switch"),)


def test_global_kill_switch_leaves_no_provider():
    switches = [KillSwitch(KillSwitchScope.GLOBAL)]
    sel = core.select_provider(["anthropic", "openai"], {"anthropic": True}, switches)
    assert sel.available is False
    assert sel.provider is None


def test_all_unhealthy_leaves_no_provider():
    sel = core.select_provider(["anthropic"], {"anthropic": False}, [])
    assert sel.provider is None
