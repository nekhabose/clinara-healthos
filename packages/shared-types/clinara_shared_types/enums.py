"""Canonical enums shared across services."""
from __future__ import annotations

from enum import Enum


class Role(str, Enum):
    """RBAC roles (spec §10.2)."""

    PLATFORM_ADMIN = "platform_administrator"
    TENANT_ADMIN = "tenant_administrator"
    CLINICAL_PROGRAMMER = "clinical_programmer"
    CLINICAL_REVIEWER = "clinical_reviewer"
    INTEGRATION_ENGINEER = "integration_engineer"
    SUPPORT_ENGINEER = "support_engineer"
    SECURITY_REVIEWER = "security_reviewer"
    READ_ONLY_AUDITOR = "read_only_auditor"
    CLINICIAN = "clinician"
    NURSE = "nurse"
    OPERATIONS_ANALYST = "operations_analyst"


class AutomationMode(str, Enum):
    """Automation modes (spec §11.2), from least to most autonomous."""

    DISABLED = "disabled"
    SHADOW = "shadow"
    SUGGESTION_ONLY = "suggestion_only"
    HUMAN_APPROVAL_REQUIRED = "human_approval_required"
    ONE_CLICK_APPROVAL = "one_click_approval"
    LIMITED_AUTO_ACTION = "limited_auto_action"
    FULL_AUTO_LOW_RISK = "full_auto_low_risk"


class ResultClassification(str, Enum):
    """Result workflow classifications (spec §6.1.4)."""

    NORMAL = "normal"
    EXPECTED_ABNORMAL = "expected_abnormal"
    CLINICALLY_INSIGNIFICANT_ABNORMAL = "clinically_insignificant_abnormal"
    ROUTINE_FOLLOW_UP = "routine_follow_up"
    CLINICIAN_REVIEW_REQUIRED = "clinician_review_required"
    HIGH_PRIORITY_REVIEW = "high_priority_review"
    CRITICAL_ESCALATION = "critical_escalation"
    UNSUPPORTED = "unsupported"
    INSUFFICIENT_DATA = "insufficient_data"
    CONFLICTING_DATA = "conflicting_data"


class MessageUrgency(str, Enum):
    """Patient message urgency levels (spec §6.2.4)."""

    EMERGENCY = "emergency"
    IMMEDIATE_CLINICIAN_REVIEW = "immediate_clinician_review"
    SAME_DAY_REVIEW = "same_day_review"
    WITHIN_24_HOURS = "within_24_hours"
    ROUTINE_CLINICAL = "routine_clinical"
    ADMINISTRATIVE = "administrative"
    INFORMATIONAL = "informational"
