"""Deterministic refill engine (plan Phase 4, workstream 3 — the second governed workflow).

A refill decision is produced by **governed, deterministic logic — never an LLM** (plan §1.1
invariant 1; spec §6.3.5). The LLM's only job downstream is to draft the *response wording*
around this decision; it can never choose to approve a refill, weaken a safety check, or
invent a medication change.

Django-free and pure so the safety-critical medication logic is exhaustively unit-testable.
The evaluation is a fixed, ordered cascade — safety exclusions first, convenience last — that
cannot be reordered by configuration:

    1. Missing medication identity   → ESCALATE_MISSING_DATA        (automation blocked)
    2. Allergy to the drug/class     → ESCALATE_CONTRAINDICATION
    3. Contraindication present      → ESCALATE_CONTRAINDICATION
    4. Interacting active medication → ROUTE_TO_PRESCRIBER
    5. Discontinued                  → REJECT_DISCONTINUED
    6. Dose mismatch                 → ROUTE_TO_PRESCRIBER          (manual review)
    7. Controlled substance          → ESCALATE_CONTROLLED_SUBSTANCE (always human)
    8. Requested too early           → REJECT_TOO_EARLY
    9. Monitoring labs overdue       → REQUEST_LABS
   10. Visit overdue                 → REQUEST_APPOINTMENT
   11. Low-risk allowlist + clean    → AUTO_APPROVE / ONE_CLICK_PREPARED
   12. Otherwise                     → ROUTE_TO_NURSE

Every branch records the exact ``clinical_factors_used`` so the decision is fully traceable
(spec §6.3.5), and the safety branches (1-7) can never be bypassed by client/clinician config.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from clinara_shared_types import RefillOutcome
from clinara_terminology import (
    LOW_RISK_REFILL_CLASSES,
    MedicationClass,
    MedicationSpec,
)


@dataclass(frozen=True)
class RefillContext:
    """The full factor set the refill engine reasons over (spec §6.3.2).

    ``medication`` is ``None`` when identity could not be resolved — which by itself blocks
    automation. Everything else is a plain, testable fact.
    """

    medication: MedicationSpec | None
    requested_dose: str | None = None
    prescribed_dose: str | None = None
    active: bool = True
    discontinued: bool = False
    days_since_last_fill: int | None = None
    days_supply: int | None = None
    last_visit_days_ago: int | None = None
    visit_required_within_days: int | None = None
    monitoring_labs_overdue: bool = False
    allergies: tuple[str, ...] = ()          # medication names / classes the patient reacts to
    contraindications: tuple[str, ...] = ()
    interactions: tuple[str, ...] = ()       # interacting active-medication names
    pregnancy: bool = False
    renal_impairment: bool = False
    hepatic_impairment: bool = False
    # Client policy: therapeutic classes this tenant permits for streamlined handling.
    client_auto_approve_classes: frozenset[MedicationClass] = field(
        default_factory=frozenset
    )


@dataclass(frozen=True)
class RefillDecision:
    """The governed, deterministic refill decision (spec §6.3.4). Immutable once produced."""

    outcome: RefillOutcome
    reason_codes: list[str]
    required_actions: list[str]
    clinical_factors_used: list[str]
    controlled_substance: bool = False
    automation_allowed: bool = False

    @property
    def requires_human(self) -> bool:
        return not self.automation_allowed


# Fraction of the days-supply that must elapse before a refill is "on time". Conservative
# and code-defined (not configurable) so "too early" is deterministic.
_EARLY_REFILL_FRACTION = 0.75


def _dose_mismatch(ctx: RefillContext) -> bool:
    if ctx.requested_dose is None or ctx.prescribed_dose is None:
        return False
    return ctx.requested_dose.strip().lower() != ctx.prescribed_dose.strip().lower()


def _too_early(ctx: RefillContext) -> bool:
    if ctx.days_since_last_fill is None or ctx.days_supply is None:
        return False
    return ctx.days_since_last_fill < ctx.days_supply * _EARLY_REFILL_FRACTION


def _visit_overdue(ctx: RefillContext) -> bool:
    if ctx.visit_required_within_days is None or ctx.last_visit_days_ago is None:
        return False
    return ctx.last_visit_days_ago > ctx.visit_required_within_days


def _decide(outcome: RefillOutcome, *, reasons: list[str], actions: list[str],
            factors: list[str], controlled: bool = False,
            automation: bool = False) -> RefillDecision:
    return RefillDecision(
        outcome=outcome, reason_codes=reasons, required_actions=actions,
        clinical_factors_used=sorted(set(factors)), controlled_substance=controlled,
        automation_allowed=automation,
    )


def evaluate_refill(ctx: RefillContext) -> RefillDecision:
    """Produce the governed refill decision. Pure, deterministic, LLM-free."""
    # 1. Missing identity blocks automation (spec §6.3.5).
    if ctx.medication is None:
        return _decide(
            RefillOutcome.ESCALATE_MISSING_DATA,
            reasons=["MEDICATION_IDENTITY_UNRESOLVED"],
            actions=["resolve_medication_identity"],
            factors=["medication.identity"],
        )

    med = ctx.medication
    name_low = med.name.lower()
    class_val = med.med_class.value

    # 2. Allergy — deterministic, never LLM (spec §6.3.5).
    if any(a.lower() in name_low or a.lower() == class_val for a in ctx.allergies):
        return _decide(
            RefillOutcome.ESCALATE_CONTRAINDICATION,
            reasons=["ALLERGY_TO_MEDICATION"],
            actions=["prescriber_review"],
            factors=["medication.name", "patient.allergies"],
        )

    # 3. Contraindication.
    if ctx.contraindications:
        return _decide(
            RefillOutcome.ESCALATE_CONTRAINDICATION,
            reasons=["CONTRAINDICATION_PRESENT"],
            actions=["prescriber_review"],
            factors=["medication.name", "patient.contraindications"],
        )

    # 4. Drug–drug interaction with an active medication.
    if ctx.interactions:
        return _decide(
            RefillOutcome.ROUTE_TO_PRESCRIBER,
            reasons=["INTERACTION_WITH_ACTIVE_MEDICATION"],
            actions=["prescriber_review"],
            factors=["medication.name", "patient.active_medications"],
        )

    # 5. Discontinued.
    if ctx.discontinued or not ctx.active:
        return _decide(
            RefillOutcome.REJECT_DISCONTINUED,
            reasons=["MEDICATION_DISCONTINUED"],
            actions=["notify_patient_discontinued"],
            factors=["medication.status"],
        )

    # 6. Dose mismatch → manual review (spec §6.3.5).
    if _dose_mismatch(ctx):
        return _decide(
            RefillOutcome.ROUTE_TO_PRESCRIBER,
            reasons=["DOSE_MISMATCH"],
            actions=["prescriber_review"],
            factors=["medication.requested_dose", "medication.prescribed_dose"],
        )

    # 7. Controlled substances follow a separate, non-overridable human path (spec §6.3.5).
    if med.is_controlled:
        return _decide(
            RefillOutcome.ESCALATE_CONTROLLED_SUBSTANCE,
            reasons=[f"CONTROLLED_SUBSTANCE_{med.schedule.value.upper()}"],
            actions=["prescriber_review", "controlled_substance_policy"],
            factors=["medication.schedule"],
            controlled=True,
        )

    # 8. Too early.
    if _too_early(ctx):
        return _decide(
            RefillOutcome.REJECT_TOO_EARLY,
            reasons=["REFILL_TOO_EARLY"],
            actions=["notify_patient_timing"],
            factors=["medication.days_since_last_fill", "medication.days_supply"],
        )

    # 9. Monitoring labs overdue.
    if ctx.monitoring_labs_overdue:
        return _decide(
            RefillOutcome.REQUEST_LABS,
            reasons=["MONITORING_LABS_OVERDUE"],
            actions=["order_monitoring_labs"],
            factors=["patient.monitoring_labs"],
        )

    # 10. Visit overdue.
    if _visit_overdue(ctx):
        return _decide(
            RefillOutcome.REQUEST_APPOINTMENT,
            reasons=["VISIT_OVERDUE"],
            actions=["schedule_appointment"],
            factors=["patient.last_visit_days_ago"],
        )

    # 11. Clean, low-risk, on-formulary → streamlined handling.
    allowlist = ctx.client_auto_approve_classes or LOW_RISK_REFILL_CLASSES
    high_risk_state = ctx.pregnancy or ctx.renal_impairment or ctx.hepatic_impairment
    if med.med_class in allowlist and not high_risk_state:
        # AUTO_APPROVE only when the client explicitly allows this class; otherwise prepare a
        # one-click item for a human (auto-approve is opt-in — spec §6.3.3).
        if med.med_class in ctx.client_auto_approve_classes:
            return _decide(
                RefillOutcome.AUTO_APPROVE,
                reasons=["LOW_RISK_CLIENT_APPROVED"],
                actions=["prepare_refill"],
                factors=["medication.class", "client.policy"],
                automation=True,
            )
        return _decide(
            RefillOutcome.ONE_CLICK_PREPARED,
            reasons=["LOW_RISK_ONE_CLICK"],
            actions=["one_click_approve"],
            factors=["medication.class"],
        )

    # 12. Everything else → a human.
    return _decide(
        RefillOutcome.ROUTE_TO_NURSE,
        reasons=["ROUTINE_REVIEW"],
        actions=["nurse_review"],
        factors=["medication.class"],
    )


__all__ = ["RefillContext", "RefillDecision", "evaluate_refill"]
