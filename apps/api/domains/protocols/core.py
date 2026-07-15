"""Pure Rule-Studio core (plan Phase 2 — simulation, impact, conflict, lifecycle).

Django-free and deterministic so the safety-critical authoring logic is exhaustively
unit-testable without a database. The Studio's promise (plan Phase 2 objective) is that a
clinical expert can *simulate*, *impact-analyze*, *approve*, *deploy* and *roll back*
clinical logic with **no application code change** — this module provides the governed
mechanics behind that promise.

Everything here operates on the same immutable ``ContextSnapshot`` + ``Rule`` primitives the
production engine (``clinara_protocol_engine``) uses, so a simulation evaluates the *exact*
logic that would run in production (plan Phase 2 testing focus: "simulated vs actual
evaluation parity").

Four capabilities:

  * **Lifecycle** — the rule state machine (spec §6.5.4) as a pure transition table.
  * **Simulation** — run current vs proposed rules over scenarios (spec §6.5.6).
  * **Impact analysis** — aggregate simulation into automation/escalation/high-risk deltas
    before activation (spec §6.5.7).
  * **Conflict detection** — precedence ambiguity across a candidate rule set; ambiguity
    degrades to *suppression*, never silent resolution (spec §6.4.3).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from clinara_clinical_models import (
    ContextProvenance,
    ContextSnapshot,
    ResultDecision,
)
from clinara_protocol_engine import LAB_FACT_ALIAS, Rule, evaluate
from clinara_protocol_engine.engine import _evaluate_condition  # reuse the engine's matcher
from clinara_shared_types import ResultClassification
from clinara_terminology import CanonicalMarker

# Facts that mark a protected / high-risk cohort — a behaviour change touching one of these
# is always surfaced prominently in the impact report (spec §6.5.7 "high-risk-cohort impact").
HIGH_RISK_FACTS: tuple[str, ...] = (
    "patient.pregnancy",
    "patient.pediatric_patient",
    "patient.renal_impairment",
    "patient.hepatic_impairment",
)

HIGH_RISK_CLASSIFICATIONS: frozenset[ResultClassification] = frozenset(
    {
        ResultClassification.CRITICAL_ESCALATION,
        ResultClassification.HIGH_PRIORITY_REVIEW,
    }
)


# --------------------------------------------------------------------------------------
# Lifecycle state machine (spec §6.5.4)
# --------------------------------------------------------------------------------------

class RuleState:
    DRAFT = "draft"
    IN_REVIEW = "in_review"
    APPROVED = "approved"
    SCHEDULED = "scheduled"
    ACTIVE = "active"
    DEPRECATED = "deprecated"
    RETIRED = "retired"
    ROLLED_BACK = "rolled_back"


# Directed transitions permitted by the governed lifecycle. Anything not listed is rejected
# so a version can never jump straight from draft to active (bypassing review/approval).
_TRANSITIONS: dict[str, frozenset[str]] = {
    RuleState.DRAFT: frozenset({RuleState.IN_REVIEW, RuleState.RETIRED}),
    RuleState.IN_REVIEW: frozenset({RuleState.APPROVED, RuleState.DRAFT, RuleState.RETIRED}),
    RuleState.APPROVED: frozenset({RuleState.SCHEDULED, RuleState.ACTIVE, RuleState.RETIRED}),
    RuleState.SCHEDULED: frozenset({RuleState.ACTIVE, RuleState.APPROVED, RuleState.RETIRED}),
    RuleState.ACTIVE: frozenset(
        {RuleState.DEPRECATED, RuleState.ROLLED_BACK, RuleState.RETIRED}
    ),
    RuleState.DEPRECATED: frozenset({RuleState.RETIRED, RuleState.ACTIVE}),
    RuleState.ROLLED_BACK: frozenset({RuleState.RETIRED, RuleState.DRAFT}),
    RuleState.RETIRED: frozenset(),
}


class IllegalTransition(ValueError):
    """Raised when a lifecycle transition is not permitted by spec §6.5.4."""


def can_transition(current: str, target: str) -> bool:
    return target in _TRANSITIONS.get(current, frozenset())


def assert_transition(current: str, target: str) -> None:
    if not can_transition(current, target):
        raise IllegalTransition(f"illegal rule transition {current!r} -> {target!r}")


# --------------------------------------------------------------------------------------
# Scenarios & snapshot construction
# --------------------------------------------------------------------------------------

@dataclass(frozen=True)
class Scenario:
    """One synthetic / de-identified case to simulate against (spec §6.5.6).

    ``facts`` is the resolved fact dict as it would appear in a ``ContextSnapshot`` (e.g.
    ``{"lab.a1c": 7.8, "patient.has_diabetes": True}``). The marker's primary alias must be
    present for the case to be meaningful.
    """

    name: str
    marker: CanonicalMarker
    facts: dict[str, Any]
    specialty: str | None = None
    conflicting_facts: tuple[str, ...] = ()

    @property
    def is_high_risk(self) -> bool:
        return any(self.facts.get(f) for f in HIGH_RISK_FACTS)


def snapshot_from_scenario(scenario: Scenario, *, tenant_id: str = "sim") -> ContextSnapshot:
    """Build the immutable snapshot the engine evaluates for a scenario (parity guarantee)."""
    facts = dict(scenario.facts)
    facts.setdefault("lab.supported", True)
    if scenario.specialty:
        facts.setdefault("context.specialty", scenario.specialty)
    provenance = ContextProvenance(
        conflicting_facts=list(scenario.conflicting_facts),
        transformations=["simulation"],
        context_builder_version="rule-studio-sim-1",
    )
    return ContextSnapshot(
        tenant_id=tenant_id,
        patient_id=f"sim:{scenario.name}",
        facts=facts,
        provenance=provenance,
        context_created_at=datetime(2026, 1, 1, tzinfo=UTC),
    )


def _decide(scenario: Scenario, rules: list[Rule]) -> tuple[ResultDecision, str | None]:
    snapshot = snapshot_from_scenario(scenario)
    ev = evaluate(snapshot, marker=scenario.marker, rules=rules, specialty=scenario.specialty)
    return ev.decision, ev.trace.matched_rule_id


# --------------------------------------------------------------------------------------
# Simulation (spec §6.5.6)
# --------------------------------------------------------------------------------------

@dataclass(frozen=True)
class SimulationCase:
    scenario: str
    high_risk: bool
    proposed_classification: str
    proposed_action: str
    proposed_matched_rule: str | None
    current_classification: str | None
    current_matched_rule: str | None
    agreement: bool
    changed_fields: list[str]
    missing_facts: list[str]


@dataclass(frozen=True)
class SimulationResult:
    cases: list[SimulationCase]

    @property
    def total(self) -> int:
        return len(self.cases)

    @property
    def changed(self) -> int:
        return sum(1 for c in self.cases if not c.agreement)

    @property
    def agreement_rate(self) -> float:
        return 1.0 if not self.cases else 1.0 - self.changed / self.total


def _missing_facts(scenario: Scenario) -> list[str]:
    alias = LAB_FACT_ALIAS[scenario.marker]
    missing = []
    if scenario.facts.get(alias) is None:
        missing.append(alias)
    return missing


def simulate(
    scenarios: list[Scenario],
    *,
    proposed_rules: list[Rule],
    current_rules: list[Rule] | None = None,
) -> SimulationResult:
    """Compare proposed vs current behaviour across scenarios (spec §6.5.6).

    ``current_rules`` may be ``None`` when the protocol is brand new (nothing to compare
    against); every case then reads as a change from "no rule".
    """
    cases: list[SimulationCase] = []
    for scenario in scenarios:
        proposed, p_rule = _decide(scenario, proposed_rules)
        if current_rules is None:
            current, c_rule = None, None
        else:
            current, c_rule = _decide(scenario, current_rules)

        changed_fields: list[str] = []
        if current is not None:
            if current.classification != proposed.classification:
                changed_fields.append("classification")
            if current.recommended_action != proposed.recommended_action:
                changed_fields.append("recommended_action")
            if current.priority != proposed.priority:
                changed_fields.append("priority")
            if current.automation_status != proposed.automation_status:
                changed_fields.append("automation_status")
        agreement = current is not None and not changed_fields

        cases.append(
            SimulationCase(
                scenario=scenario.name,
                high_risk=scenario.is_high_risk
                or proposed.classification in HIGH_RISK_CLASSIFICATIONS,
                proposed_classification=proposed.classification.value,
                proposed_action=proposed.recommended_action,
                proposed_matched_rule=p_rule,
                current_classification=current.classification.value if current else None,
                current_matched_rule=c_rule,
                agreement=agreement,
                changed_fields=changed_fields,
                missing_facts=_missing_facts(scenario),
            )
        )
    return SimulationResult(cases=cases)


# --------------------------------------------------------------------------------------
# Impact analysis (spec §6.5.7)
# --------------------------------------------------------------------------------------

@dataclass(frozen=True)
class ImpactReport:
    total_cases: int
    changed_cases: int
    high_risk_changed: list[str]
    classification_deltas: dict[str, int]  # "before->after" -> count
    automation_rate_before: float
    automation_rate_after: float
    escalation_rate_before: float
    escalation_rate_after: float
    conflicts: list[ConflictFinding]
    missing_data_scenarios: list[str]

    @property
    def safe_to_activate(self) -> bool:
        """No unresolved precedence conflict may reach production (spec §6.4.3)."""
        return not self.conflicts


def _escalates(classification: str | None) -> bool:
    return classification in {
        ResultClassification.CRITICAL_ESCALATION.value,
        ResultClassification.HIGH_PRIORITY_REVIEW.value,
    }


def impact_report(
    scenarios: list[Scenario],
    *,
    proposed_rules: list[Rule],
    current_rules: list[Rule] | None = None,
) -> ImpactReport:
    """Aggregate a simulation into the pre-activation impact report (spec §6.5.7)."""
    sim = simulate(scenarios, proposed_rules=proposed_rules, current_rules=current_rules)
    deltas: dict[str, int] = {}
    high_risk_changed: list[str] = []
    missing: list[str] = []
    auto_before = auto_after = esc_before = esc_after = 0

    for case in sim.cases:
        if not case.agreement:
            key = f"{case.current_classification}->{case.proposed_classification}"
            deltas[key] = deltas.get(key, 0) + 1
            if case.high_risk:
                high_risk_changed.append(case.scenario)
        if case.missing_facts:
            missing.append(case.scenario)
        # Automation/escalation rates (proposed side always defined; current may be None).
        if _automates_from_status(case.current_classification, current_rules is not None):
            auto_before += 1
        auto_after += 1 if _automation_ok(case.proposed_classification) else 0
        esc_before += 1 if _escalates(case.current_classification) else 0
        esc_after += 1 if _escalates(case.proposed_classification) else 0

    n = max(1, sim.total)
    conflicts = detect_conflicts(scenarios, rules=proposed_rules)
    return ImpactReport(
        total_cases=sim.total,
        changed_cases=sim.changed,
        high_risk_changed=high_risk_changed,
        classification_deltas=deltas,
        automation_rate_before=round(auto_before / n, 4),
        automation_rate_after=round(auto_after / n, 4),
        escalation_rate_before=round(esc_before / n, 4),
        escalation_rate_after=round(esc_after / n, 4),
        conflicts=conflicts,
        missing_data_scenarios=missing,
    )


def _automation_ok(classification: str | None) -> bool:
    # A proxy: normal/routine classifications are the ones eligible for streamlined handling.
    return classification in {
        ResultClassification.NORMAL.value,
        ResultClassification.ROUTINE_FOLLOW_UP.value,
        ResultClassification.CLINICALLY_INSIGNIFICANT_ABNORMAL.value,
        ResultClassification.EXPECTED_ABNORMAL.value,
    }


def _automates_from_status(classification: str | None, had_current: bool) -> bool:
    return had_current and _automation_ok(classification)


# --------------------------------------------------------------------------------------
# Conflict detection (spec §6.4.3 — ambiguity → suppression, never silent resolution)
# --------------------------------------------------------------------------------------

@dataclass(frozen=True)
class ConflictFinding:
    scenario: str
    marker: str
    rule_ids: list[str]
    classifications: list[str]


def _rule_matches(rule: Rule, scenario: Scenario) -> bool:
    if rule.marker != scenario.marker.value:
        return False
    if rule.scope.specialties and scenario.specialty not in rule.scope.specialties:
        return False
    if any(scenario.facts.get(f) for f in rule.safety.excluded_when):
        return False
    return _evaluate_condition(rule.when, scenario.facts)


def _precedence(rule: Rule) -> tuple[int, int]:
    """Higher = more specific. Specialty-scoped rules outrank global; newer version wins."""
    return (1 if rule.scope.specialties else 0, rule.version)


def detect_conflicts(scenarios: list[Scenario], *, rules: list[Rule]) -> list[ConflictFinding]:
    """Flag scenarios where ≥2 equal-precedence rules match with differing outcomes.

    The engine resolves such ties by first-match, but for governance we surface them: an
    ambiguous configuration must *suppress automation* rather than silently pick a winner
    (spec §6.4.3). Rules of strictly higher precedence unambiguously win and are not a
    conflict.
    """
    findings: list[ConflictFinding] = []
    for scenario in scenarios:
        matched = [r for r in rules if _rule_matches(r, scenario)]
        if len(matched) < 2:
            continue
        top = max(_precedence(r) for r in matched)
        top_rules = [r for r in matched if _precedence(r) == top]
        classifications = {r.then.classification for r in top_rules}
        if len(top_rules) >= 2 and len(classifications) >= 2:
            findings.append(
                ConflictFinding(
                    scenario=scenario.name,
                    marker=scenario.marker.value,
                    rule_ids=sorted(r.id for r in top_rules),
                    classifications=sorted(classifications),
                )
            )
    return findings


# --------------------------------------------------------------------------------------
# Safety guard — the Studio physically cannot weaken engine-enforced safety (plan Phase 2)
# --------------------------------------------------------------------------------------

class SafetyViolation(ValueError):
    """Raised when an authored rule attempts to weaken a non-negotiable safety floor."""


def assert_cannot_weaken_safety(rule: Rule, scenarios: list[Scenario]) -> None:
    """Reject a rule that would (attempt to) down-classify a critical result.

    Critical thresholds live in code and are evaluated *before* rules, so a rule can never
    actually override them — but we still refuse to *store* a rule that tries, so authors
    get an immediate, explicit error instead of a silently-inert rule (plan Phase 2 risk:
    "authors bypassing safety").
    """
    from clinara_protocol_engine import critical_breach

    for scenario in scenarios:
        if scenario.marker.value != rule.marker:
            continue
        alias = LAB_FACT_ALIAS[scenario.marker]
        value = scenario.facts.get(alias)
        if value is None:
            continue
        breach = critical_breach(scenario.marker, float(value))
        if breach is None:
            continue
        if not _rule_matches(rule, scenario):
            continue
        # The scenario is a critical value AND this rule claims a non-critical outcome.
        if rule.then.classification != ResultClassification.CRITICAL_ESCALATION.value:
            raise SafetyViolation(
                f"rule {rule.id!r} would down-classify a critical value "
                f"({breach}) on scenario {scenario.name!r}"
            )


# --------------------------------------------------------------------------------------
# Release bundle (plan Phase 2 deliverable — content-addressed config artifact)
# --------------------------------------------------------------------------------------

@dataclass(frozen=True)
class TestCaseResult:
    name: str
    passed: bool
    expected: str
    actual: str


def run_test_cases(rule_scenarios: list[tuple[Scenario, str]], rules: list[Rule]) -> list[
    TestCaseResult
]:
    """Evaluate each (scenario, expected_classification) pair against ``rules``.

    A version cannot activate unless every attached test case passes (plan Phase 2
    deliverable: "a rule cannot activate if its required test cases fail").
    """
    results: list[TestCaseResult] = []
    for scenario, expected in rule_scenarios:
        decision, _ = _decide(scenario, rules)
        actual = decision.classification.value
        results.append(
            TestCaseResult(
                name=scenario.name, passed=actual == expected, expected=expected, actual=actual
            )
        )
    return results


__all__ = [
    "RuleState",
    "can_transition",
    "assert_transition",
    "IllegalTransition",
    "Scenario",
    "snapshot_from_scenario",
    "SimulationCase",
    "SimulationResult",
    "simulate",
    "ImpactReport",
    "impact_report",
    "ConflictFinding",
    "detect_conflicts",
    "SafetyViolation",
    "assert_cannot_weaken_safety",
    "TestCaseResult",
    "run_test_cases",
    "HIGH_RISK_FACTS",
]
