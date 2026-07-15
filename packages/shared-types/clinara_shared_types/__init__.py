"""Shared cross-service types: the domain event envelope and canonical enums."""

from .enums import (
    AutomationMode,
    MessageUrgency,
    ResultClassification,
    Role,
)
from .events import DomainEvent, EventType

__all__ = [
    "DomainEvent",
    "EventType",
    "AutomationMode",
    "MessageUrgency",
    "ResultClassification",
    "Role",
]
