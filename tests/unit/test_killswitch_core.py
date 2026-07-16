"""Kill-switch resolution core (GA hardening — spec §11.4).

Django-free; runs with PYTHONPATH=apps/api. Proves the safety invariants: a broader switch
is never overridden by a narrower one, ambiguous attempts are denied, and the broadest cause
is reported.
"""
from clinara_shared_types import KillSwitchScope

from domains.killswitch import core


def _attempt(**kw):
    return core.AutomationAttempt(**kw)


def test_no_switches_allows_automation():
    d = core.resolve(_attempt(tenant_id="t1", workflow="results"), [])
    assert d.allowed is True
    assert d.suppressed is False


def test_global_switch_suppresses_everything():
    d = core.resolve(
        _attempt(tenant_id="t1", workflow="results"),
        [core.KillSwitch(KillSwitchScope.GLOBAL, reason="incident", engaged_by="oncall")],
    )
    assert d.suppressed is True
    assert d.scope is KillSwitchScope.GLOBAL
    assert d.reason == "incident"
    assert d.engaged_by == "oncall"


def test_workflow_switch_matches_only_its_target():
    switches = [core.KillSwitch(KillSwitchScope.WORKFLOW, target="refills")]
    assert core.resolve(_attempt(workflow="refills"), switches).suppressed is True
    assert core.resolve(_attempt(workflow="results"), switches).suppressed is False


def test_broadest_switch_is_reported_as_cause():
    # Both a tenant and a workflow switch match; the tenant (broader) must be the cause.
    switches = [
        core.KillSwitch(KillSwitchScope.WORKFLOW, target="results", reason="w"),
        core.KillSwitch(KillSwitchScope.TENANT, target="t1", reason="t"),
    ]
    d = core.resolve(_attempt(tenant_id="t1", workflow="results"), switches)
    assert d.scope is KillSwitchScope.TENANT
    assert d.reason == "t"
    assert len(d.matched) == 2  # both surfaced for operators


def test_narrower_enable_cannot_override_broader_disable():
    # There is no "enable" switch — only suppressions. A global suppression stands regardless
    # of any narrower-scope state, which is the whole point of the fail-safe design.
    d = core.resolve(
        _attempt(tenant_id="t1", clinician="dr_a"),
        [core.KillSwitch(KillSwitchScope.GLOBAL)],
    )
    assert d.suppressed is True
    assert d.scope is KillSwitchScope.GLOBAL


def test_unattributed_attempt_is_denied_on_ambiguity():
    # Attempt doesn't say which workflow it is; a workflow switch still covers it.
    switches = [core.KillSwitch(KillSwitchScope.WORKFLOW, target="results")]
    d = core.resolve(_attempt(workflow=None), switches)
    assert d.suppressed is True


def test_attributed_attempt_outside_target_is_allowed():
    switches = [core.KillSwitch(KillSwitchScope.CLINICIAN, target="dr_a")]
    assert core.resolve(_attempt(clinician="dr_b"), switches).allowed is True


def test_all_ten_scopes_are_enforceable():
    # Every spec §11.4 scope must be able to suppress a fully-attributed matching attempt.
    attempt = _attempt(
        tenant_id="t1",
        site="s1",
        specialty="cardiology",
        workflow="results",
        protocol="a1c_v3",
        clinician="dr_a",
        model_provider="anthropic",
        integration="epic",
        communication_channel="portal",
    )
    targets = {
        KillSwitchScope.GLOBAL: "*",
        KillSwitchScope.TENANT: "t1",
        KillSwitchScope.SITE: "s1",
        KillSwitchScope.SPECIALTY: "cardiology",
        KillSwitchScope.WORKFLOW: "results",
        KillSwitchScope.PROTOCOL: "a1c_v3",
        KillSwitchScope.CLINICIAN: "dr_a",
        KillSwitchScope.MODEL_PROVIDER: "anthropic",
        KillSwitchScope.INTEGRATION: "epic",
        KillSwitchScope.COMMUNICATION_CHANNEL: "portal",
    }
    assert set(targets) == set(KillSwitchScope)  # no scope left untested
    for scope, target in targets.items():
        d = core.resolve(attempt, [core.KillSwitch(scope, target=target)])
        assert d.suppressed is True, scope


def test_llm_provider_suppressed_helper():
    switches = [core.KillSwitch(KillSwitchScope.MODEL_PROVIDER, target="anthropic")]
    assert core.llm_provider_suppressed("anthropic", switches) is True
    assert core.llm_provider_suppressed("openai", switches) is False


def test_global_switch_kills_every_provider():
    switches = [core.KillSwitch(KillSwitchScope.GLOBAL)]
    assert core.llm_provider_suppressed("anthropic", switches) is True
    assert core.llm_provider_suppressed("anything", switches) is True
