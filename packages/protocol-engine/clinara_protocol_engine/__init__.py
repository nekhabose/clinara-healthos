"""Clinara deterministic protocol engine (plan Phase 1 — the crown jewel).

Evaluates versioned declarative rules against an immutable context snapshot to produce a
structured, replayable ``ResultDecision`` — before any LLM is involved. Critical
thresholds and other safety gates run ahead of rules and cannot be weakened by config.
"""

from .critical import CRITICAL_THRESHOLDS, CriticalRange, critical_breach
from .engine import LAB_FACT_ALIAS, evaluate
from .loader import load_rule, load_rules
from .operators import OPERATORS, UnknownOperatorError, apply_operator
from .schema import (
    BoolCondition,
    Condition,
    LeafCondition,
    Rule,
    RuleSafety,
    RuleScope,
    RuleThen,
)

__all__ = [
    "evaluate",
    "LAB_FACT_ALIAS",
    "load_rule",
    "load_rules",
    "Rule",
    "RuleScope",
    "RuleThen",
    "RuleSafety",
    "Condition",
    "LeafCondition",
    "BoolCondition",
    "OPERATORS",
    "apply_operator",
    "UnknownOperatorError",
    "critical_breach",
    "CRITICAL_THRESHOLDS",
    "CriticalRange",
]
