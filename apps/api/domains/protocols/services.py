"""Clinical Rule Studio service interface (spec §7.4, plan Phase 2).

The ONLY entry point for authoring, simulating, approving, deploying, and rolling back
clinical logic. Every mutation is audited and (where it changes deployed behaviour) emits a
domain event. The governed guarantees enforced here:

  * A version moves only along the legal lifecycle (spec §6.5.4) — draft → review → approved
    → scheduled → active → deprecated/retired/rolled-back. Illegal jumps raise.
  * A version cannot **activate** unless (a) it is dual-approved, (b) every attached test
    case passes, and (c) no unresolved precedence conflict exists in the resulting active
    set — otherwise automation is suppressed (spec §6.4.3).
  * A version cannot be **stored/deployed** if it would down-classify a critical value — the
    Studio physically cannot weaken the engine-enforced safety floor (plan Phase 2 risk).

Persistence + the pure Studio mechanics (``protocols.core``) are kept apart so the
governance logic is unit-testable without a database.
"""
from __future__ import annotations

import uuid
from typing import Any

from clinara_protocol_engine import Rule
from clinara_shared_types import EventType
from clinara_terminology import CanonicalMarker
from django.db import transaction
from django.utils import timezone

from clinara.middleware.phi_safe_logging import correlation_id as _correlation_id
from clinara.middleware.tenant import current_tenant_id, set_db_tenant
from core.outbox import publish_event
from domains.audit import services as audit

from . import core
from .core import RuleState, Scenario
from .models import (
    Deployment,
    DeploymentMode,
    DeploymentStatus,
    Protocol,
    ProtocolVersion,
    Rollback,
    RuleTestCase,
    SimulationRun,
)


def _bind(tenant_id: str) -> None:
    current_tenant_id.set(str(tenant_id))
    _correlation_id.set(str(uuid.uuid4()))
    set_db_tenant(str(tenant_id))


def _scenario_from(marker: str, facts: dict, specialty: str | None,
                   name: str, conflicting: list[str] | None = None) -> Scenario:
    return Scenario(
        name=name, marker=CanonicalMarker(marker), facts=facts,
        specialty=specialty or None, conflicting_facts=tuple(conflicting or []),
    )


def _rule_of(version: ProtocolVersion) -> Rule:
    return Rule.model_validate(version.rule_body)


def _active_rules(tenant_id: str, marker: str, *, exclude_version_id: str | None = None,
                  include: Rule | None = None) -> list[Rule]:
    """The rule set that is (or would be) live for a marker in this tenant.

    The Studio governs tenant-authored rules; ``include`` injects the candidate rule being
    activated so conflict/impact analysis see the resulting set.
    """
    qs = ProtocolVersion.objects.filter(
        tenant_id=tenant_id, protocol__marker=marker, state=RuleState.ACTIVE
    )
    if exclude_version_id:
        qs = qs.exclude(id=exclude_version_id)
    rules = [_rule_of(v) for v in qs]
    if include is not None:
        rules = [r for r in rules if r.id != include.id] + [include]
    return rules


# ---- Authoring -----------------------------------------------------------------------

def create_protocol(*, tenant_id: str, key: str, marker: str, title: str,
                    description: str = "", actor: str = "system") -> Protocol:
    _bind(tenant_id)
    with transaction.atomic():
        protocol = Protocol.objects.create(
            tenant_id=tenant_id, key=key, marker=marker, title=title, description=description
        )
        audit.record(actor=actor, action="protocol_created",
                     resource=f"protocol:{protocol.id}", reason=key,
                     after_state={"key": key, "marker": marker})
    return protocol


def create_version(*, tenant_id: str, protocol_id: str, rule_body: dict,
                   author: str = "system", evidence_references: list[str] | None = None
                   ) -> ProtocolVersion:
    """Author a new draft version. Rejects a body that isn't a valid rule for the protocol."""
    _bind(tenant_id)
    rule = Rule.model_validate(rule_body)  # type-safe: malformed rule fails loudly here
    protocol = Protocol.objects.get(id=protocol_id, tenant_id=tenant_id)
    if rule.marker != protocol.marker:
        raise ValueError(f"rule marker {rule.marker!r} != protocol marker {protocol.marker!r}")

    with transaction.atomic():
        last = (
            ProtocolVersion.objects.filter(tenant_id=tenant_id, protocol=protocol)
            .order_by("-version").values_list("version", flat=True).first()
        )
        version = ProtocolVersion.objects.create(
            tenant_id=tenant_id, protocol=protocol, version=(last or 0) + 1,
            rule_body=rule_body, author=author,
            evidence_references=evidence_references or [], state=RuleState.DRAFT,
        )
        audit.record(actor=author, action="protocol_version_authored",
                     resource=f"protocol_version:{version.id}", reason=f"v{version.version}",
                     after_state={"state": RuleState.DRAFT, "version": version.version})
    return version


def add_test_case(*, tenant_id: str, version_id: str, name: str, marker: str,
                  facts: dict, expected_classification: str, specialty: str = "",
                  conflicting_facts: list[str] | None = None) -> RuleTestCase:
    _bind(tenant_id)
    version = ProtocolVersion.objects.get(id=version_id, tenant_id=tenant_id)
    return RuleTestCase.objects.create(
        tenant_id=tenant_id, version=version, name=name, marker=marker, facts=facts,
        specialty=specialty, conflicting_facts=conflicting_facts or [],
        expected_classification=expected_classification,
    )


# ---- Simulation & impact -------------------------------------------------------------

def _scenarios_for(version: ProtocolVersion, extra: list[dict] | None = None) -> list[Scenario]:
    scenarios = [
        _scenario_from(tc.marker, tc.facts, tc.specialty, tc.name, tc.conflicting_facts)
        for tc in version.test_cases.all()
    ]
    for i, s in enumerate(extra or []):
        scenarios.append(
            _scenario_from(
                s.get("marker", version.protocol.marker), s.get("facts", {}),
                s.get("specialty"), s.get("name", f"adhoc_{i}"), s.get("conflicting_facts"),
            )
        )
    return scenarios


def simulate(*, tenant_id: str, version_id: str, scenarios: list[dict] | None = None,
             actor: str = "system") -> SimulationRun:
    """Run the version's rule against its test cases + any ad-hoc scenarios (spec §6.5.6)."""
    _bind(tenant_id)
    version = ProtocolVersion.objects.get(id=version_id, tenant_id=tenant_id)
    proposed = _rule_of(version)
    cases = _scenarios_for(version, scenarios)
    current = _active_rules(tenant_id, version.protocol.marker, exclude_version_id=version_id)
    result = core.simulate(cases, proposed_rules=[proposed], current_rules=current or None)

    with transaction.atomic():
        run = SimulationRun.objects.create(
            tenant_id=tenant_id, version=version, scenario_count=result.total,
            changed_count=result.changed, agreement_rate=result.agreement_rate,
            cases=[c.__dict__ for c in result.cases],
        )
        audit.record(actor=actor, action="protocol_simulated",
                     resource=f"protocol_version:{version.id}",
                     after_state={"agreement_rate": result.agreement_rate,
                                  "changed": result.changed})
        publish_event(
            event_type=EventType.PROTOCOL_SIMULATED.value,
            idempotency_key=f"{version.id}:sim:{run.id}",
            payload={"version_id": str(version.id), "agreement_rate": result.agreement_rate},
        )
    return run


def analyze_impact(*, tenant_id: str, version_id: str,
                   scenarios: list[dict] | None = None) -> dict[str, Any]:
    """Produce + persist the pre-activation impact report (spec §6.5.7)."""
    _bind(tenant_id)
    version = ProtocolVersion.objects.get(id=version_id, tenant_id=tenant_id)
    proposed = _rule_of(version)
    cases = _scenarios_for(version, scenarios)
    current = _active_rules(tenant_id, version.protocol.marker, exclude_version_id=version_id)
    proposed_set = _active_rules(
        tenant_id, version.protocol.marker, exclude_version_id=version_id, include=proposed
    )
    report = core.impact_report(cases, proposed_rules=proposed_set, current_rules=current or None)
    payload = {
        "total_cases": report.total_cases,
        "changed_cases": report.changed_cases,
        "high_risk_changed": report.high_risk_changed,
        "classification_deltas": report.classification_deltas,
        "automation_rate_before": report.automation_rate_before,
        "automation_rate_after": report.automation_rate_after,
        "escalation_rate_before": report.escalation_rate_before,
        "escalation_rate_after": report.escalation_rate_after,
        "conflicts": [c.__dict__ for c in report.conflicts],
        "missing_data_scenarios": report.missing_data_scenarios,
        "safe_to_activate": report.safe_to_activate,
    }
    version.impact_report = payload
    version.save(update_fields=["impact_report", "updated_at"])
    return payload


# ---- Lifecycle -----------------------------------------------------------------------

def _transition(version: ProtocolVersion, target: str, actor: str, reason: str = "",
                extra_after: dict | None = None) -> ProtocolVersion:
    core.assert_transition(version.state, target)
    before = version.state
    version.state = target
    version.save(update_fields=["state", "updated_at"])
    after = {"state": target}
    if extra_after:
        after.update(extra_after)
    audit.record(actor=actor, action="protocol_state_change",
                 resource=f"protocol_version:{version.id}", reason=reason or target,
                 before_state={"state": before}, after_state=after)
    return version


def submit_for_review(*, tenant_id: str, version_id: str, actor: str = "system"):
    _bind(tenant_id)
    with transaction.atomic():
        version = ProtocolVersion.objects.get(id=version_id, tenant_id=tenant_id)
        return _transition(version, RuleState.IN_REVIEW, actor)


def approve(*, tenant_id: str, version_id: str, actor: str, role: str) -> ProtocolVersion:
    """Record a dual-approval sign-off. ``role`` is 'clinical' or 'engineering'.

    The version advances to ``approved`` only once BOTH sign-offs are present (spec §6.5.4).
    """
    if role not in {"clinical", "engineering"}:
        raise ValueError("approval role must be 'clinical' or 'engineering'")
    _bind(tenant_id)
    with transaction.atomic():
        version = ProtocolVersion.objects.get(id=version_id, tenant_id=tenant_id)
        if version.state not in {RuleState.IN_REVIEW, RuleState.APPROVED}:
            raise core.IllegalTransition(f"cannot approve from state {version.state!r}")
        if role == "clinical":
            version.clinical_approved_by = actor
        else:
            version.engineering_approved_by = actor
        version.save(update_fields=[f"{role}_approved_by", "updated_at"])
        audit.record(actor=actor, action="protocol_approval",
                     resource=f"protocol_version:{version.id}", reason=role,
                     after_state={"role": role, "dual_approved": version.dual_approved})
        if version.dual_approved and version.state == RuleState.IN_REVIEW:
            _transition(version, RuleState.APPROVED, actor, reason="dual_approved")
            publish_event(
                event_type=EventType.PROTOCOL_APPROVED.value,
                idempotency_key=f"{version.id}:approved",
                payload={"version_id": str(version.id)},
            )
    return version


class ActivationBlocked(RuntimeError):
    """Raised when a version fails the activation gate (tests / approval / conflict)."""


def _run_test_gate(tenant_id: str, version: ProtocolVersion) -> list[dict]:
    """Validate the authored rule's OWN declared behaviour (activation gate).

    Test cases assert what *this* rule does in isolation — the engine still evaluates the
    un-weakenable critical floor ahead of it. Cross-rule interaction is a separate concern
    handled by conflict detection (which suppresses automation rather than failing the
    gate), so a rule's regression suite is deterministic regardless of what else is live.
    """
    proposed = _rule_of(version)
    pairs = [
        (_scenario_from(tc.marker, tc.facts, tc.specialty, tc.name, tc.conflicting_facts),
         tc.expected_classification)
        for tc in version.test_cases.all()
    ]
    results = core.run_test_cases(pairs, [proposed])
    return [r.__dict__ for r in results]


def deploy(*, tenant_id: str, version_id: str, mode: str = DeploymentMode.SHADOW,
           rollout_percentage: int = 100, target_scope: dict | None = None,
           monitoring_plan: dict | None = None, actor: str = "system") -> Deployment:
    """Deploy a version (shadow → progressive → full). Enforces the activation gate.

    Gate (plan Phase 2 exit criteria):
      * version must be dual-approved,
      * every attached test case must pass,
      * a critical-weakening rule is refused,
      * an unresolved precedence conflict suppresses automation (recorded on the
        deployment) rather than silently resolving (spec §6.4.3).
    """
    if mode not in DeploymentMode.values:
        raise ValueError(f"unknown deployment mode {mode!r}")
    _bind(tenant_id)
    with transaction.atomic():
        version = ProtocolVersion.objects.select_for_update().get(
            id=version_id, tenant_id=tenant_id
        )
        proposed = _rule_of(version)

        # Safety floor: refuse a rule that would down-classify a critical value.
        core.assert_cannot_weaken_safety(proposed, _scenarios_for(version))

        # Dual approval required for anything that ACTS. Shadow may run on an
        # approved-but-not-yet-live version to gather agreement data first.
        if not version.dual_approved:
            raise ActivationBlocked("version is not dual-approved")

        # Regression gate.
        test_results = _run_test_gate(tenant_id, version)
        failed = [r for r in test_results if not r["passed"]]
        version.test_results = test_results
        version.save(update_fields=["test_results", "updated_at"])
        if failed:
            raise ActivationBlocked(
                f"{len(failed)} test case(s) failing: {[r['name'] for r in failed]}"
            )

        # Conflict detection over the resulting active set.
        proposed_set = _active_rules(
            tenant_id, version.protocol.marker,
            exclude_version_id=str(version.id), include=proposed,
        )
        conflicts = core.detect_conflicts(_scenarios_for(version), rules=proposed_set)

        deployment = Deployment.objects.create(
            tenant_id=tenant_id, version=version, mode=mode,
            rollout_percentage=rollout_percentage, target_scope=target_scope or {},
            monitoring_plan=monitoring_plan or {}, deployed_by=actor,
            conflicts_suppressed=bool(conflicts),
            rollback_to_version=_current_active_version_number(
                tenant_id, version.protocol_id, exclude_version_id=str(version.id)
            ),
        )

        # Shadow mode observes only; progressive/full make the version live.
        if mode in {DeploymentMode.PROGRESSIVE, DeploymentMode.FULL}:
            _supersede_active_versions(tenant_id, version.protocol_id, exclude=str(version.id),
                                       actor=actor)
            if version.state != RuleState.ACTIVE:
                _transition(version, RuleState.ACTIVE, actor, reason=f"deploy:{mode}")

        audit.record(actor=actor, action="protocol_deployed",
                     resource=f"deployment:{deployment.id}", reason=mode,
                     after_state={"mode": mode, "conflicts_suppressed": bool(conflicts),
                                  "rollout_percentage": rollout_percentage})
        publish_event(
            event_type=EventType.PROTOCOL_DEPLOYED.value,
            idempotency_key=f"{deployment.id}:deployed",
            payload={"version_id": str(version.id), "deployment_id": str(deployment.id),
                     "mode": mode, "conflicts_suppressed": bool(conflicts)},
        )
    return deployment


def _current_active_version_number(tenant_id: str, protocol_id: str,
                                   exclude_version_id: str) -> int | None:
    return (
        ProtocolVersion.objects.filter(
            tenant_id=tenant_id, protocol_id=protocol_id, state=RuleState.ACTIVE
        ).exclude(id=exclude_version_id).order_by("-version")
        .values_list("version", flat=True).first()
    )


def _supersede_active_versions(tenant_id: str, protocol_id: str, exclude: str,
                               actor: str) -> None:
    for v in ProtocolVersion.objects.filter(
        tenant_id=tenant_id, protocol_id=protocol_id, state=RuleState.ACTIVE
    ).exclude(id=exclude):
        _transition(v, RuleState.DEPRECATED, actor, reason="superseded")


def rollback(*, tenant_id: str, deployment_id: str, reason: str,
             automatic: bool = False, actor: str = "system") -> Rollback:
    """Roll a deployment back to its recorded safe version (spec §6.5.8)."""
    _bind(tenant_id)
    with transaction.atomic():
        deployment = Deployment.objects.select_for_update().get(
            id=deployment_id, tenant_id=tenant_id
        )
        version = deployment.version
        record = Rollback.objects.create(
            tenant_id=tenant_id, deployment=deployment, from_version=version.version,
            to_version=deployment.rollback_to_version, automatic=automatic,
            reason=reason, actor=actor,
        )
        deployment.status = DeploymentStatus.ROLLED_BACK
        deployment.save(update_fields=["status", "updated_at"])
        if version.state == RuleState.ACTIVE:
            _transition(version, RuleState.ROLLED_BACK, actor, reason=f"rollback:{reason}")
        # Restore the prior version to active if one was recorded.
        if deployment.rollback_to_version is not None:
            prior = ProtocolVersion.objects.filter(
                tenant_id=tenant_id, protocol_id=version.protocol_id,
                version=deployment.rollback_to_version,
            ).first()
            if prior is not None and prior.state == RuleState.DEPRECATED:
                _transition(prior, RuleState.ACTIVE, actor, reason="restored_on_rollback")
        audit.record(actor=actor, action="protocol_rolled_back",
                     resource=f"deployment:{deployment.id}", reason=reason,
                     after_state={"automatic": automatic,
                                  "to_version": deployment.rollback_to_version})
        publish_event(
            event_type=EventType.PROTOCOL_ROLLED_BACK.value,
            idempotency_key=f"{deployment.id}:rollback:{record.id}",
            payload={"deployment_id": str(deployment.id), "reason": reason,
                     "automatic": automatic},
        )
    return record


def build_release_bundle(*, tenant_id: str, version_id: str) -> dict[str, Any]:
    """The versioned config-release bundle (plan Phase 2 deliverable).

    A self-describing artifact: rule body, approval record, impact report, test results,
    target scope, rollout + rollback + monitoring plan. This is what a config release ships
    — distinct from an application code release (spec §14.3).
    """
    _bind(tenant_id)
    version = ProtocolVersion.objects.get(id=version_id, tenant_id=tenant_id)
    latest_deploy = version.deployments.order_by("-created_at").first()
    return {
        "protocol_key": version.protocol.key,
        "marker": version.protocol.marker,
        "version": version.version,
        "state": version.state,
        "rule_body": version.rule_body,
        "evidence_references": version.evidence_references,
        "approval": {
            "clinical": version.clinical_approved_by or None,
            "engineering": version.engineering_approved_by or None,
            "dual_approved": version.dual_approved,
        },
        "impact_report": version.impact_report,
        "test_results": version.test_results,
        "effective_date": timezone.now().date().isoformat(),
        "target_scope": latest_deploy.target_scope if latest_deploy else {},
        "rollout_plan": {
            "mode": latest_deploy.mode if latest_deploy else None,
            "rollout_percentage": latest_deploy.rollout_percentage if latest_deploy else None,
        },
        "rollback_version": latest_deploy.rollback_to_version if latest_deploy else None,
        "monitoring_plan": latest_deploy.monitoring_plan if latest_deploy else {},
    }


__all__ = [
    "create_protocol", "create_version", "add_test_case", "simulate", "analyze_impact",
    "submit_for_review", "approve", "deploy", "rollback", "build_release_bundle",
    "ActivationBlocked",
]
