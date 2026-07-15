"""Deterministic protocol engine v1 (plan Phase 1, workstream 5 — the crown jewel).

Evaluates versioned declarative rules against an immutable context snapshot and produces a
structured ``ResultDecision`` (spec §6.1.5). The engine is a *pure function* of its inputs:
same snapshot + same rules → same decision, always. No LLM, no I/O, no clock.

Safety ordering is fixed and cannot be reordered by configuration (plan §1.1):

    1. Unsupported unit           → block interpretation      (UNSUPPORTED)
    2. Missing primary value      → suppress automation       (INSUFFICIENT_DATA)
    3. Conflicting facts          → require manual review      (CONFLICTING_DATA)
    4. Critical threshold breach  → escalate, bypass queues    (CRITICAL_ESCALATION)
    5. First matching rule        → its declared outcome
    6. No rule                    → reference-range default    (NORMAL / CLINICIAN_REVIEW)

Steps 1–4 run BEFORE any rule and can never be weakened by a rule, tenant, or clinician.
"""
from __future__ import annotations

from clinara_clinical_models import (
    ContextSnapshot,
    EvaluationTrace,
    ProtocolEvaluation,
    ResultDecision,
)
from clinara_shared_types import AutomationStatus, Priority, RecommendedAction, ResultClassification
from clinara_terminology import LAB_FACT_ALIAS, CanonicalMarker

from .critical import critical_breach
from .operators import apply_operator
from .schema import BoolCondition, Condition, LeafCondition, Rule

# ``LAB_FACT_ALIAS`` — the fact name each canonical marker's primary value is published under,
# so rules read against friendly names (e.g. ``lab.a1c``) — is DERIVED from the terminology
# catalog (``MarkerSpec.fact_alias``) rather than hand-maintained here. That makes adding a
# marker for a new specialty a pure data change: the crown-jewel evaluator is never edited to
# grow protocol breadth (plan Phase 10). Re-exported for backward compatibility.
__all_alias__ = LAB_FACT_ALIAS  # noqa: F841 (documents the re-export intent)

_PRIORITY_BY_CLASSIFICATION: dict[ResultClassification, Priority] = {
    ResultClassification.NORMAL: Priority.NORMAL,
    ResultClassification.EXPECTED_ABNORMAL: Priority.NORMAL,
    ResultClassification.CLINICALLY_INSIGNIFICANT_ABNORMAL: Priority.NORMAL,
    ResultClassification.ROUTINE_FOLLOW_UP: Priority.NORMAL,
    ResultClassification.CLINICIAN_REVIEW_REQUIRED: Priority.ELEVATED,
    ResultClassification.HIGH_PRIORITY_REVIEW: Priority.URGENT,
    ResultClassification.CRITICAL_ESCALATION: Priority.CRITICAL,
    ResultClassification.UNSUPPORTED: Priority.NORMAL,
    ResultClassification.INSUFFICIENT_DATA: Priority.NORMAL,
    ResultClassification.CONFLICTING_DATA: Priority.ELEVATED,
}


def _classification(value: str) -> ResultClassification:
    try:
        return ResultClassification(value)
    except ValueError as exc:  # fail loud: a rule naming an unknown classification is a bug
        raise ValueError(f"rule declares unknown classification {value!r}") from exc


def _leaf_facts(condition: Condition, acc: set[str]) -> None:
    if isinstance(condition, LeafCondition):
        acc.add(condition.fact)
    elif isinstance(condition, BoolCondition):
        for sub in condition.all or condition.any or []:
            _leaf_facts(sub, acc)
        if condition.not_ is not None:
            _leaf_facts(condition.not_, acc)


def _evaluate_condition(condition: Condition, facts: dict) -> bool:
    if isinstance(condition, LeafCondition):
        if condition.fact not in facts or facts[condition.fact] is None:
            return False  # a missing fact never satisfies a predicate
        return apply_operator(condition.operator, facts[condition.fact], condition.value)
    # BoolCondition
    if condition.all is not None:
        return all(_evaluate_condition(c, facts) for c in condition.all)
    if condition.any is not None:
        return any(_evaluate_condition(c, facts) for c in condition.any)
    assert condition.not_ is not None
    return not _evaluate_condition(condition.not_, facts)


def _safety_decision(
    marker: CanonicalMarker,
    classification: ResultClassification,
    automation: AutomationStatus,
    reason: str,
    action: str = RecommendedAction.REQUEST_MANUAL_REVIEW,
) -> ProtocolEvaluation:
    decision = ResultDecision(
        classification=classification,
        priority=_PRIORITY_BY_CLASSIFICATION[classification],
        recommended_action=action,
        automation_status=automation,
        patient_message_template=None,
        reason_codes=[reason],
        clinical_facts_used=[LAB_FACT_ALIAS[marker]],
    )
    trace = EvaluationTrace(marker=marker.value, notes=[reason])
    return ProtocolEvaluation(decision=decision, trace=trace)


def evaluate(
    snapshot: ContextSnapshot,
    *,
    marker: CanonicalMarker,
    rules: list[Rule],
    specialty: str | None = None,
) -> ProtocolEvaluation:
    """Produce the governed decision for ``marker`` from ``snapshot`` and ``rules``."""
    facts = snapshot.facts
    alias = LAB_FACT_ALIAS[marker]

    # 1. Unsupported unit blocks interpretation (spec §6.1.6).
    if facts.get("lab.supported") is False:
        return _safety_decision(
            marker,
            ResultClassification.UNSUPPORTED,
            AutomationStatus.BLOCKED_UNSUPPORTED,
            "UNSUPPORTED_UNIT",
            action=RecommendedAction.NONE,
        )

    # 2. Missing primary value suppresses automation (spec §6.1.6).
    value = facts.get(alias)
    if value is None:
        return _safety_decision(
            marker,
            ResultClassification.INSUFFICIENT_DATA,
            AutomationStatus.SUPPRESSED_MISSING_CONTEXT,
            "MISSING_PRIMARY_VALUE",
        )

    # 3. Conflicting facts require manual review (spec §6.1.6).
    if snapshot.provenance.conflicting_facts:
        return _safety_decision(
            marker,
            ResultClassification.CONFLICTING_DATA,
            AutomationStatus.MANUAL_REVIEW_REQUIRED,
            "CONFLICTING_DATA",
        )

    # 4. Critical thresholds — evaluated before rules, un-weakenable (spec §6.1.6).
    breach = critical_breach(marker, float(value))
    if breach is not None:
        decision = ResultDecision(
            classification=ResultClassification.CRITICAL_ESCALATION,
            priority=Priority.CRITICAL,
            recommended_action=RecommendedAction.ESCALATE_IMMEDIATELY,
            automation_status=AutomationStatus.MANUAL_REVIEW_REQUIRED,
            patient_message_template=None,  # criticals go to a clinician, never straight to a patient
            reason_codes=[breach],
            clinical_facts_used=[alias],
        )
        trace = EvaluationTrace(marker=marker.value, critical_triggered=True, notes=[breach])
        return ProtocolEvaluation(decision=decision, trace=trace)

    # 5. First matching rule wins.
    considered: list[str] = []
    for rule in sorted(rules, key=lambda r: r.version, reverse=True):
        if rule.marker != marker.value:
            continue
        if rule.scope.specialties and specialty not in rule.scope.specialties:
            continue
        considered.append(f"{rule.id}@{rule.version}")
        if any(facts.get(f) for f in rule.safety.excluded_when):
            continue  # protected cohort — this rule does not apply
        if not _evaluate_condition(rule.when, facts):
            continue

        classification = _classification(rule.then.classification)
        automation = (
            AutomationStatus.MANUAL_REVIEW_REQUIRED
            if rule.safety.requires_manual_review
            else AutomationStatus.REQUIRES_CLINICIAN_APPROVAL
        )
        used: set[str] = {alias}
        _leaf_facts(rule.when, used)
        used.update(rule.then.clinician_context)
        priority = (
            Priority(rule.then.priority)
            if rule.then.priority
            else _PRIORITY_BY_CLASSIFICATION[classification]
        )
        decision = ResultDecision(
            classification=classification,
            priority=priority,
            recommended_action=rule.then.recommended_action,
            recommended_interval_days=rule.then.recommended_interval_days,
            automation_status=automation,
            patient_message_template=rule.then.patient_template,
            reason_codes=rule.then.reason_codes or [f"RULE_{rule.id.upper()}_MATCHED"],
            clinical_facts_used=sorted(used),
        )
        trace = EvaluationTrace(
            marker=marker.value,
            matched_rule_id=rule.id,
            matched_rule_version=rule.version,
            rules_considered=considered,
        )
        return ProtocolEvaluation(decision=decision, trace=trace)

    # 6. No rule matched — safe reference-range default.
    ref_low = facts.get("lab.ref_low")
    ref_high = facts.get("lab.ref_high")
    within = True
    if ref_low is not None and float(value) < float(ref_low):
        within = False
    if ref_high is not None and float(value) > float(ref_high):
        within = False

    if within:
        classification = ResultClassification.NORMAL
        action = RecommendedAction.NONE
        reason = "WITHIN_REFERENCE_RANGE"
    else:
        classification = ResultClassification.CLINICIAN_REVIEW_REQUIRED
        action = RecommendedAction.CLINICIAN_REVIEW
        reason = "OUTSIDE_REFERENCE_RANGE"

    decision = ResultDecision(
        classification=classification,
        priority=_PRIORITY_BY_CLASSIFICATION[classification],
        recommended_action=action,
        automation_status=AutomationStatus.REQUIRES_CLINICIAN_APPROVAL,
        patient_message_template=None,
        reason_codes=[reason],
        clinical_facts_used=[alias],
    )
    trace = EvaluationTrace(
        marker=marker.value, rules_considered=considered, notes=["no_rule_matched"]
    )
    return ProtocolEvaluation(decision=decision, trace=trace)
