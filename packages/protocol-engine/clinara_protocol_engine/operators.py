"""Type-safe rule operators (plan Phase 2 §6.5.5 "type-safe operators").

Kept tiny and total: every operator is a pure comparison with no side effects, so a rule
evaluation is deterministic and replayable. Unknown operators raise rather than silently
failing open.
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any


def _as_number(v: Any) -> float:
    if isinstance(v, bool):  # guard: bool is an int subclass; never compare it numerically
        raise TypeError("boolean value used in a numeric comparison")
    return float(v)


def _numeric(op: Callable[[float, float], bool]) -> Callable[[Any, Any], bool]:
    def apply(fact: Any, value: Any) -> bool:
        return op(_as_number(fact), _as_number(value))

    return apply


OPERATORS: dict[str, Callable[[Any, Any], bool]] = {
    "equals": lambda fact, value: fact == value,
    "not_equals": lambda fact, value: fact != value,
    "greater_than": _numeric(lambda a, b: a > b),
    "greater_than_or_equal": _numeric(lambda a, b: a >= b),
    "less_than": _numeric(lambda a, b: a < b),
    "less_than_or_equal": _numeric(lambda a, b: a <= b),
    "in": lambda fact, value: fact in value,
    "not_in": lambda fact, value: fact not in value,
}


class UnknownOperatorError(KeyError):
    pass


def apply_operator(operator: str, fact_value: Any, target_value: Any) -> bool:
    fn = OPERATORS.get(operator)
    if fn is None:
        raise UnknownOperatorError(operator)
    return fn(fact_value, target_value)
