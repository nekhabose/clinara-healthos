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
    # GA hardening (spec §10.2): emergency, time-boxed, fully-audited privileged access.
    EMERGENCY_RESPONDER = "emergency_responder"


class KillSwitchScope(str, Enum):
    """Automation kill-switch scopes (spec §11.4), broadest → narrowest.

    A switch at any scope suppresses automation for everything within it. Order matters:
    ``resolve`` walks this precedence so a GLOBAL disable can never be overridden by a
    narrower enable, and the broadest matching active switch is reported as the cause.
    """

    GLOBAL = "global"
    TENANT = "tenant"
    SITE = "site"
    SPECIALTY = "specialty"
    WORKFLOW = "workflow"
    PROTOCOL = "protocol"
    CLINICIAN = "clinician"
    MODEL_PROVIDER = "model_provider"
    INTEGRATION = "integration"
    COMMUNICATION_CHANNEL = "communication_channel"


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


class RefillOutcome(str, Enum):
    """Prescription-refill outcomes (spec §6.3.3). Ordered least → most escalated.

    ``auto_approve`` is reserved for an explicitly approved low-risk allowlist with all
    deterministic safety preconditions clean; everything else routes to a human. Controlled
    substances always take the ``escalate_controlled_substance`` path (spec §6.3.5).
    """

    AUTO_APPROVE = "auto_approve"
    ONE_CLICK_PREPARED = "one_click_prepared"
    ROUTE_TO_NURSE = "route_to_nurse"
    ROUTE_TO_PRESCRIBER = "route_to_prescriber"
    REQUEST_LABS = "request_labs"
    REQUEST_APPOINTMENT = "request_appointment"
    REJECT_TOO_EARLY = "reject_too_early"
    REJECT_DISCONTINUED = "reject_discontinued"
    ESCALATE_CONTRAINDICATION = "escalate_contraindication"
    ESCALATE_MISSING_DATA = "escalate_missing_data"
    ESCALATE_CONTROLLED_SUBSTANCE = "escalate_controlled_substance"


class Priority(str, Enum):
    """Result priority band (spec §6.1.5 ``priority``). Drives queue placement."""

    NORMAL = "normal"
    ELEVATED = "elevated"
    URGENT = "urgent"
    CRITICAL = "critical"


class AutomationStatus(str, Enum):
    """What may happen to a decision without further computation (spec §6.1.5).

    Phase 1 ships human-approval-required only; auto-delivery is architecturally absent.
    ``suppressed_missing_context`` and ``blocked_unsupported`` are safety states that can
    never be auto-resolved (spec §6.1.6).
    """

    REQUIRES_CLINICIAN_APPROVAL = "requires_clinician_approval"
    MANUAL_REVIEW_REQUIRED = "manual_review_required"
    SUPPRESSED_MISSING_CONTEXT = "suppressed_missing_context"
    BLOCKED_UNSUPPORTED = "blocked_unsupported"


# Recommended-action vocabulary (spec §6.1.5 ``recommended_action``). Rules emit these as
# strings; the constants document the governed set without forcing an enum on rule authors.
class RecommendedAction:
    NONE = "none"
    REPEAT_TEST = "repeat_test"
    EVALUATE_CURRENT_PLAN = "evaluate_current_plan"
    ROUTINE_FOLLOW_UP = "routine_follow_up"
    CLINICIAN_REVIEW = "clinician_review"
    ESCALATE_IMMEDIATELY = "escalate_immediately"
    REQUEST_MANUAL_REVIEW = "request_manual_review"
