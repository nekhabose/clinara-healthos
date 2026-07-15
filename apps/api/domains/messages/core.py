"""Patient Message Intelligence — deterministic core (plan Phase 5; spec §6.2).

This is the most LLM-dependent module, deliberately last so the deterministic safety
scaffolding is battle-tested first. The governing invariant (plan §1.1; spec §6.2.6):

    A deterministic red-flag detector is the safety FLOOR. The LLM classifier may only
    *raise* concern above that floor — it can NEVER lower urgency below the deterministic
    result, and model confidence alone NEVER determines urgency.

Everything here is pure and Django-free so the safety-critical triage logic is exhaustively
unit-testable. Four capabilities:

  * **Red-flag detection** — rule-based emergency detection over the verbatim message,
    multilingual, run *independently of and in addition to* classification (spec §6.2.6).
  * **Classification & extraction** — a swappable ``Classifier`` (the LLM's role); the
    default is a deterministic keyword classifier so tests are hermetic. Its confidence is
    never used to set urgency.
  * **Urgency assignment** — deterministic combination of the red-flag floor and the
    category baseline (spec §6.2.4).
  * **Identity / contamination guard** — prevents cross-patient context contamination
    before any chart-based reasoning (spec §6.2.6).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Protocol

from clinara_shared_types import MessageUrgency

# --------------------------------------------------------------------------------------
# Category taxonomy (spec §6.2.2)
# --------------------------------------------------------------------------------------

class MessageCategory(str, Enum):
    CLINICAL_SYMPTOM = "clinical_symptom"
    MEDICATION_QUESTION = "medication_question"
    TEST_RESULT_INQUIRY = "test_result_inquiry"
    APPOINTMENT = "appointment"
    ADMINISTRATIVE = "administrative"
    BILLING = "billing"
    PRESCRIPTION_REFILL = "prescription_refill"
    GENERAL_QUESTION = "general_question"
    OTHER = "other"


# Urgency ordering, most → least urgent. Lower index = more urgent (used to take the max).
_URGENCY_ORDER: list[MessageUrgency] = [
    MessageUrgency.EMERGENCY,
    MessageUrgency.IMMEDIATE_CLINICIAN_REVIEW,
    MessageUrgency.SAME_DAY_REVIEW,
    MessageUrgency.WITHIN_24_HOURS,
    MessageUrgency.ROUTINE_CLINICAL,
    MessageUrgency.ADMINISTRATIVE,
    MessageUrgency.INFORMATIONAL,
]
_URGENCY_RANK = {u: i for i, u in enumerate(_URGENCY_ORDER)}


def most_urgent(a: MessageUrgency, b: MessageUrgency) -> MessageUrgency:
    """Return the MORE urgent of two levels (lower rank index wins)."""
    return a if _URGENCY_RANK[a] <= _URGENCY_RANK[b] else b


# --------------------------------------------------------------------------------------
# Deterministic red-flag detection (spec §6.2.6) — the safety floor
# --------------------------------------------------------------------------------------

@dataclass(frozen=True)
class RedFlagRule:
    code: str
    urgency: MessageUrgency
    patterns: tuple[str, ...]  # lowercase substrings; multilingual (EN + ES seed)


# Conservative, high-recall emergency rules. Recall is the priority: a missed escalation is
# a release blocker (plan Phase 5 testing focus), so these err toward escalating.
RED_FLAG_RULES: tuple[RedFlagRule, ...] = (
    RedFlagRule("RED_FLAG_CHEST_PAIN", MessageUrgency.EMERGENCY,
                ("chest pain", "chest pressure", "crushing chest", "dolor en el pecho",
                 "dolor de pecho")),
    RedFlagRule("RED_FLAG_BREATHING", MessageUrgency.EMERGENCY,
                ("can't breathe", "cannot breathe", "trouble breathing",
                 "difficulty breathing", "short of breath", "no puedo respirar")),
    RedFlagRule("RED_FLAG_SUICIDAL", MessageUrgency.EMERGENCY,
                ("suicidal", "suicide", "kill myself", "end my life", "want to die",
                 "hurt myself", "harm myself", "suicidarme", "quitarme la vida")),
    RedFlagRule("RED_FLAG_STROKE", MessageUrgency.EMERGENCY,
                ("drooping", "slurred", "sudden weakness", "one side of my body",
                 "can't move my arm", "cara caída")),
    RedFlagRule("RED_FLAG_SEVERE_BLEEDING", MessageUrgency.EMERGENCY,
                ("severe bleeding", "won't stop bleeding", "heavy bleeding",
                 "coughing up blood", "sangrado severo")),
    RedFlagRule("RED_FLAG_ANAPHYLAXIS", MessageUrgency.EMERGENCY,
                ("throat swelling", "throat is swelling", "throat is closing",
                 "anaphylaxis", "tongue swelling")),
    RedFlagRule("RED_FLAG_WORST_HEADACHE", MessageUrgency.IMMEDIATE_CLINICIAN_REVIEW,
                ("worst headache", "worst headache of my life", "thunderclap headache")),
    RedFlagRule("RED_FLAG_SUDDEN_VISION_LOSS", MessageUrgency.IMMEDIATE_CLINICIAN_REVIEW,
                ("sudden vision loss", "lost my vision", "can't see")),
)


@dataclass(frozen=True)
class RedFlagResult:
    flags: list[str]
    urgency: MessageUrgency | None  # None → no red flag

    @property
    def has_emergency(self) -> bool:
        return self.urgency is MessageUrgency.EMERGENCY


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text.lower()).strip()


def detect_red_flags(text: str) -> RedFlagResult:
    """Scan the VERBATIM message for emergency red flags. Independent of any model output.

    This runs on the raw patient text, so an attempt to hide or downplay an emergency in
    surrounding prose (or a prompt-injection instruction) cannot suppress it.
    """
    norm = _normalize(text)
    flags: list[str] = []
    urgency: MessageUrgency | None = None
    for rule in RED_FLAG_RULES:
        if any(p in norm for p in rule.patterns):
            flags.append(rule.code)
            urgency = rule.urgency if urgency is None else most_urgent(urgency, rule.urgency)
    return RedFlagResult(flags=flags, urgency=urgency)


# --------------------------------------------------------------------------------------
# Classification & extraction (the LLM's role — swappable, confidence never sets urgency)
# --------------------------------------------------------------------------------------

@dataclass(frozen=True)
class Classification:
    category: MessageCategory
    confidence: float
    symptoms: list[str] = field(default_factory=list)
    medications: list[str] = field(default_factory=list)
    requested_action: str | None = None
    summary: str = ""


class Classifier(Protocol):
    def classify(self, text: str, *, language: str) -> Classification: ...


# Keyword → category signals for the deterministic default classifier. A production system
# swaps in an LLM classifier implementing the same protocol; the governance around it
# (red-flag floor, urgency assignment) is unchanged.
_CATEGORY_SIGNALS: list[tuple[MessageCategory, tuple[str, ...]]] = [
    (MessageCategory.PRESCRIPTION_REFILL, ("refill", "renew my prescription", "out of my",
                                           "need more of my")),
    (MessageCategory.MEDICATION_QUESTION, ("side effect", "dose", "medication", "pill",
                                           "should i take", "interaction")),
    (MessageCategory.TEST_RESULT_INQUIRY, ("my results", "lab result", "test result",
                                           "bloodwork", "a1c")),
    (MessageCategory.APPOINTMENT, ("appointment", "reschedule", "book", "schedule a visit")),
    (MessageCategory.BILLING, ("bill", "invoice", "charge", "insurance", "copay")),
    (MessageCategory.CLINICAL_SYMPTOM, ("pain", "fever", "rash", "cough", "nausea",
                                        "dizzy", "symptom", "hurts", "swelling", "vomit")),
    (MessageCategory.ADMINISTRATIVE, ("form", "records", "referral", "letter", "address")),
]


class RuleBasedClassifier:
    """Deterministic default classifier (stands in for the LLM in tests / offline)."""

    def classify(self, text: str, *, language: str) -> Classification:
        norm = _normalize(text)
        for category, signals in _CATEGORY_SIGNALS:
            if any(s in norm for s in signals):
                symptoms = [s for s in ("pain", "fever", "rash", "cough", "nausea",
                                        "swelling") if s in norm]
                return Classification(
                    category=category, confidence=0.9, symptoms=symptoms,
                    summary=f"Patient message classified as {category.value}.",
                )
        return Classification(category=MessageCategory.GENERAL_QUESTION, confidence=0.5,
                              summary="General patient question.")


# --------------------------------------------------------------------------------------
# Deterministic urgency assignment (spec §6.2.4)
# --------------------------------------------------------------------------------------

_URGENCY_BY_CATEGORY: dict[MessageCategory, MessageUrgency] = {
    MessageCategory.CLINICAL_SYMPTOM: MessageUrgency.SAME_DAY_REVIEW,
    MessageCategory.MEDICATION_QUESTION: MessageUrgency.WITHIN_24_HOURS,
    MessageCategory.TEST_RESULT_INQUIRY: MessageUrgency.ROUTINE_CLINICAL,
    MessageCategory.PRESCRIPTION_REFILL: MessageUrgency.WITHIN_24_HOURS,
    MessageCategory.APPOINTMENT: MessageUrgency.ADMINISTRATIVE,
    MessageCategory.BILLING: MessageUrgency.ADMINISTRATIVE,
    MessageCategory.ADMINISTRATIVE: MessageUrgency.ADMINISTRATIVE,
    MessageCategory.GENERAL_QUESTION: MessageUrgency.INFORMATIONAL,
    MessageCategory.OTHER: MessageUrgency.ROUTINE_CLINICAL,
}


@dataclass(frozen=True)
class UrgencyDecision:
    urgency: MessageUrgency
    red_flags: list[str]
    category: MessageCategory
    reason_codes: list[str]

    @property
    def is_emergency(self) -> bool:
        return self.urgency is MessageUrgency.EMERGENCY


def assign_urgency(red_flags: RedFlagResult, classification: Classification) -> UrgencyDecision:
    """Combine the red-flag floor with the category baseline — never model confidence.

    Final urgency is the MORE urgent of (red-flag urgency, category urgency). The classifier
    can raise concern via its category, but the red-flag floor can never be lowered — so the
    system never falsely reassures when a red flag is present (spec §6.2.6).
    """
    category_urgency = _URGENCY_BY_CATEGORY[classification.category]
    reason_codes: list[str] = [f"CATEGORY_{classification.category.value.upper()}"]
    final = category_urgency
    if red_flags.urgency is not None:
        final = most_urgent(final, red_flags.urgency)
        reason_codes = red_flags.flags + reason_codes
    return UrgencyDecision(
        urgency=final, red_flags=red_flags.flags,
        category=classification.category, reason_codes=reason_codes,
    )


# --------------------------------------------------------------------------------------
# Identity / cross-patient contamination guard (spec §6.2.6)
# --------------------------------------------------------------------------------------

class ContaminationError(ValueError):
    """Raised when chart reasoning would cross patient boundaries."""


def validate_identity(*, message_patient_id: str, context_patient_id: str) -> None:
    """Ensure the chart being reasoned over belongs to the message's patient.

    A mismatch means context was assembled for the wrong patient — reasoning must stop
    before any chart-based inference (spec §6.2.6 cross-patient contamination guard).
    """
    if str(message_patient_id) != str(context_patient_id):
        raise ContaminationError(
            f"patient identity mismatch: message={message_patient_id} "
            f"context={context_patient_id}"
        )


# --------------------------------------------------------------------------------------
# Routing & response drafting (spec §6.2)
# --------------------------------------------------------------------------------------

class Destination(str, Enum):
    EMERGENCY_ESCALATION = "emergency_escalation"
    CLINICIAN = "clinician"
    NURSE = "nurse"
    ADMIN_POOL = "admin_pool"


# Categories that may receive an auto-drafted response (non-clinical, low-risk). Anything
# clinical is never fully auto-resolved (spec §6.2 — high-risk categories to a human).
_AUTO_RESPONSE_CATEGORIES = frozenset(
    {MessageCategory.APPOINTMENT, MessageCategory.BILLING, MessageCategory.ADMINISTRATIVE}
)


@dataclass(frozen=True)
class RoutingDecision:
    destination: Destination
    auto_resolvable: bool
    escalated: bool


def route(decision: UrgencyDecision) -> RoutingDecision:
    """Route by urgency + category. Emergencies escalate now; clinical never auto-resolves."""
    if decision.urgency is MessageUrgency.EMERGENCY:
        return RoutingDecision(Destination.EMERGENCY_ESCALATION, auto_resolvable=False,
                               escalated=True)
    if decision.urgency in (MessageUrgency.IMMEDIATE_CLINICIAN_REVIEW,
                            MessageUrgency.SAME_DAY_REVIEW):
        return RoutingDecision(Destination.CLINICIAN, auto_resolvable=False, escalated=False)
    if decision.category in _AUTO_RESPONSE_CATEGORIES and not decision.red_flags:
        return RoutingDecision(Destination.ADMIN_POOL, auto_resolvable=True, escalated=False)
    return RoutingDecision(Destination.NURSE, auto_resolvable=False, escalated=False)


# --------------------------------------------------------------------------------------
# Language detection (spec §6.2 — preserve verbatim, detect for multilingual handling)
# --------------------------------------------------------------------------------------

_SPANISH_MARKERS = ("dolor", "no puedo", "necesito", "por favor", "gracias", "medicamento",
                    "cita", "suicidarme")


def detect_language(text: str) -> str:
    norm = _normalize(text)
    if any(m in norm for m in _SPANISH_MARKERS):
        return "es"
    return "en"


__all__ = [
    "MessageCategory", "MessageUrgency", "RedFlagResult", "detect_red_flags",
    "Classification", "Classifier", "RuleBasedClassifier", "UrgencyDecision",
    "assign_urgency", "most_urgent", "ContaminationError", "validate_identity",
    "Destination", "RoutingDecision", "route", "detect_language",
]
