"""Clinical Rule Studio — service-layer lifecycle (plan Phase 2 exit gate).

DB-backed (SQLite by default). Proves a clinical programmer can author → simulate →
impact-analyze → dual-approve → deploy (shadow → progressive) → roll back a rule with NO
application code change, and that every governed guard holds: illegal lifecycle jumps, the
dual-approval + regression-test activation gate, conflict-driven automation suppression, the
un-weakenable critical safety floor, audit completeness, and outbox events.
"""
import uuid

import pytest

from core.models import DomainEventOutbox
from domains.audit.models import AuditEvent
from domains.protocols import services as protocols
from domains.protocols.core import IllegalTransition, SafetyViolation
from domains.protocols.models import Deployment, ProtocolVersion

pytestmark = pytest.mark.django_db


def _tenant() -> str:
    return str(uuid.uuid4())


def _a1c_body(version=1, threshold=7.0, classification="clinician_review_required"):
    return {
        "id": "a1c_above_target", "version": version, "marker": "hemoglobin_a1c",
        "scope": {"specialties": ["primary_care"]},
        "when": {"all": [
            {"fact": "patient.has_diabetes", "operator": "equals", "value": True},
            {"fact": "lab.a1c", "operator": "greater_than_or_equal", "value": threshold},
        ]},
        "then": {"classification": classification,
                 "recommended_action": "evaluate_current_plan",
                 "reason_codes": ["A1C_ABOVE_CONFIGURED_TARGET"]},
        "safety": {"excluded_when": ["patient.pregnancy"]},
    }


def _author_version(t, *, body=None):
    protocol = protocols.create_protocol(
        tenant_id=t, key="a1c-mgmt", marker="hemoglobin_a1c", title="A1C management"
    )
    version = protocols.create_version(
        tenant_id=t, protocol_id=str(protocol.id), rule_body=body or _a1c_body(),
        author="dr_clinical",
    )
    protocols.add_test_case(
        tenant_id=t, version_id=str(version.id), name="above_target_positive",
        marker="hemoglobin_a1c", specialty="primary_care",
        facts={"lab.a1c": 7.8, "patient.has_diabetes": True},
        expected_classification="clinician_review_required",
    )
    return protocol, version


def _dual_approve(t, version):
    protocols.submit_for_review(tenant_id=t, version_id=str(version.id))
    protocols.approve(tenant_id=t, version_id=str(version.id), actor="dr_clin", role="clinical")
    protocols.approve(tenant_id=t, version_id=str(version.id), actor="eng_lead", role="engineering")


def test_full_authoring_to_deploy_no_code_change():
    t = _tenant()
    _, version = _author_version(t)

    run = protocols.simulate(tenant_id=t, version_id=str(version.id))
    assert run.scenario_count == 1

    report = protocols.analyze_impact(tenant_id=t, version_id=str(version.id))
    assert report["safe_to_activate"] is True

    _dual_approve(t, version)
    version.refresh_from_db()
    assert version.state == "approved"
    assert version.dual_approved is True

    deployment = protocols.deploy(
        tenant_id=t, version_id=str(version.id), mode="progressive", rollout_percentage=25,
        actor="eng_lead",
    )
    version.refresh_from_db()
    assert version.state == "active"
    assert deployment.status == "active"


def test_deploy_blocked_without_dual_approval():
    t = _tenant()
    _, version = _author_version(t)
    protocols.submit_for_review(tenant_id=t, version_id=str(version.id))
    protocols.approve(tenant_id=t, version_id=str(version.id), actor="dr_clin", role="clinical")
    # Only clinical sign-off → activation gate blocks deploy.
    with pytest.raises(protocols.ActivationBlocked):
        protocols.deploy(tenant_id=t, version_id=str(version.id), mode="progressive")


def test_deploy_blocked_when_test_case_fails():
    t = _tenant()
    protocol, version = _author_version(t)
    # Attach a test case the rule cannot satisfy → regression gate blocks activation.
    protocols.add_test_case(
        tenant_id=t, version_id=str(version.id), name="impossible",
        marker="hemoglobin_a1c", specialty="primary_care",
        facts={"lab.a1c": 7.8, "patient.has_diabetes": True},
        expected_classification="normal",
    )
    _dual_approve(t, version)
    with pytest.raises(protocols.ActivationBlocked):
        protocols.deploy(tenant_id=t, version_id=str(version.id), mode="progressive")


def test_illegal_lifecycle_transition_rejected():
    t = _tenant()
    _, version = _author_version(t)
    # draft → approve directly is illegal (must pass through review first).
    with pytest.raises(IllegalTransition):
        protocols.approve(tenant_id=t, version_id=str(version.id), actor="x", role="clinical")


def test_rule_weakening_a_critical_is_refused_at_deploy():
    t = _tenant()
    body = {
        "id": "k_soft", "version": 1, "marker": "potassium",
        "when": {"all": [{"fact": "lab.potassium", "operator": "greater_than", "value": 5.5}]},
        "then": {"classification": "routine_follow_up"},
    }
    protocol = protocols.create_protocol(
        tenant_id=t, key="k-mgmt", marker="potassium", title="Potassium"
    )
    version = protocols.create_version(
        tenant_id=t, protocol_id=str(protocol.id), rule_body=body, author="x"
    )
    protocols.add_test_case(
        tenant_id=t, version_id=str(version.id), name="k_critical", marker="potassium",
        facts={"lab.potassium": 6.8}, expected_classification="critical_escalation",
    )
    _dual_approve(t, version)
    with pytest.raises(SafetyViolation):
        protocols.deploy(tenant_id=t, version_id=str(version.id), mode="progressive")


def test_conflict_suppresses_automation_on_deploy():
    t = _tenant()
    protocol, v1 = _author_version(t)
    _dual_approve(t, v1)
    protocols.deploy(tenant_id=t, version_id=str(v1.id), mode="progressive")

    # A second, different protocol whose rule also matches the same scenario, same
    # precedence, different outcome → conflict → automation suppressed.
    p2 = protocols.create_protocol(
        tenant_id=t, key="a1c-alt", marker="hemoglobin_a1c", title="A1C alt"
    )
    alt_body = {
        "id": "a1c_alt", "version": 1, "marker": "hemoglobin_a1c",
        "scope": {"specialties": ["primary_care"]},
        "when": {"all": [{"fact": "lab.a1c", "operator": "greater_than_or_equal", "value": 7.0}]},
        "then": {"classification": "routine_follow_up"},
    }
    v2 = protocols.create_version(tenant_id=t, protocol_id=str(p2.id), rule_body=alt_body)
    protocols.add_test_case(
        tenant_id=t, version_id=str(v2.id), name="alt_case", marker="hemoglobin_a1c",
        specialty="primary_care", facts={"lab.a1c": 7.8, "patient.has_diabetes": True},
        expected_classification="routine_follow_up",
    )
    _dual_approve(t, v2)
    deployment = protocols.deploy(tenant_id=t, version_id=str(v2.id), mode="progressive")
    assert deployment.conflicts_suppressed is True


def test_rollback_restores_prior_version():
    t = _tenant()
    protocol, v1 = _author_version(t)
    _dual_approve(t, v1)
    protocols.deploy(tenant_id=t, version_id=str(v1.id), mode="full")

    v2 = protocols.create_version(
        tenant_id=t, protocol_id=str(protocol.id), rule_body=_a1c_body(version=2, threshold=8.0)
    )
    protocols.add_test_case(
        tenant_id=t, version_id=str(v2.id), name="v2_case", marker="hemoglobin_a1c",
        specialty="primary_care", facts={"lab.a1c": 8.5, "patient.has_diabetes": True},
        expected_classification="clinician_review_required",
    )
    _dual_approve(t, v2)
    d2 = protocols.deploy(tenant_id=t, version_id=str(v2.id), mode="full")
    v1.refresh_from_db()
    assert v1.state == "deprecated"  # superseded by v2

    protocols.rollback(tenant_id=t, deployment_id=str(d2.id), reason="agreement drop",
                       automatic=True)
    v2.refresh_from_db()
    v1.refresh_from_db()
    assert v2.state == "rolled_back"
    assert v1.state == "active"  # prior version restored


def test_shadow_mode_does_not_activate():
    t = _tenant()
    _, version = _author_version(t)
    _dual_approve(t, version)
    protocols.deploy(tenant_id=t, version_id=str(version.id), mode="shadow")
    version.refresh_from_db()
    assert version.state == "approved"  # shadow observes only; not yet live


def test_release_bundle_is_self_describing():
    t = _tenant()
    _, version = _author_version(t)
    protocols.analyze_impact(tenant_id=t, version_id=str(version.id))
    _dual_approve(t, version)
    protocols.deploy(tenant_id=t, version_id=str(version.id), mode="progressive",
                     rollout_percentage=25, target_scope={"specialties": ["primary_care"]},
                     monitoring_plan={"metric": "agreement_rate", "threshold": 0.9})
    bundle = protocols.build_release_bundle(tenant_id=t, version_id=str(version.id))
    assert bundle["approval"]["dual_approved"] is True
    assert bundle["rollout_plan"]["mode"] == "progressive"
    assert bundle["target_scope"] == {"specialties": ["primary_care"]}
    assert bundle["monitoring_plan"]["threshold"] == 0.9
    assert all(r["passed"] for r in bundle["test_results"])


def test_lifecycle_is_audited_and_emits_events():
    t = _tenant()
    _, version = _author_version(t)
    _dual_approve(t, version)
    protocols.deploy(tenant_id=t, version_id=str(version.id), mode="progressive")
    assert AuditEvent.objects.filter(tenant_id=t, action="protocol_deployed").exists()
    assert AuditEvent.objects.filter(tenant_id=t, action="protocol_approval").count() == 2
    types = set(DomainEventOutbox.objects.filter(tenant_id=t).values_list("event_type", flat=True))
    assert {"ProtocolApproved", "ProtocolDeployed"} <= types


def test_tenant_scoping_isolates_protocols():
    a, b = _tenant(), _tenant()
    _author_version(a)
    assert ProtocolVersion.objects.filter(tenant_id=a).count() == 1
    assert ProtocolVersion.objects.filter(tenant_id=b).count() == 0
    assert Deployment.objects.filter(tenant_id=b).count() == 0
