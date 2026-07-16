"""Shared cross-service types: the domain event envelope and canonical enums."""

from .enums import (
    AutomationMode,
    AutomationStatus,
    KillSwitchScope,
    MessageUrgency,
    Priority,
    RecommendedAction,
    RefillOutcome,
    ResultClassification,
    Role,
)
from .events import DomainEvent, EventType

__all__ = [
    "DomainEvent",
    "EventType",
    "AutomationMode",
    "AutomationStatus",
    "KillSwitchScope",
    "MessageUrgency",
    "Priority",
    "RecommendedAction",
    "RefillOutcome",
    "ResultClassification",
    "Role",
]
