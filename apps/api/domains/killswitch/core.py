"""Automation kill-switch resolution (GA hardening — spec §11.4, §11.3).

The kill switch is the platform's emergency brake: a switch active at ANY scope suppresses
automation for everything inside that scope. This module is the pure, Django-free decision
core — a set of active switches plus the context of one automation attempt in, a single
``KillSwitchDecision`` out. Persistence, the ops API, and audit live in the Django layer.

Design invariants (why this is a safety component, not a feature flag):
  * **Broadest wins, fail-safe.** ``resolve`` walks scopes broadest → narrowest and reports
    the *broadest* active switch as the cause. A GLOBAL disable can never be overridden by a
    narrower enable — there is no "enable" switch at all; a switch only ever *suppresses*.
  * **Deny on ambiguity.** An attempt that cannot be fully attributed (e.g. a model-provider
    or workflow that isn't identified in the context) is treated as covered by any switch at
    that scope, never waved through.
  * **Deterministic + explainable.** Every suppression names the exact scope and target that
    caused it, so the decision trace (spec §12.4) can replay *why* automation stopped.

This composes with automation eligibility (spec §11.3, ``current model status`` and
``incident state``): eligibility calls ``resolve`` and, if suppressed, routes the case to a
human instead of acting. It never *lowers* a safety decision — only removes automation.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from clinara_shared_types import KillSwitchScope

# Broadest → narrowest. Precedence for reporting the causing switch and for the fail-safe
# rule that a broader switch is never overridden by a narrower one.
SCOPE_PRECEDENCE: tuple[KillSwitchScope, ...] = (
    KillSwitchScope.GLOBAL,
    KillSwitchScope.TENANT,
    KillSwitchScope.SITE,
    KillSwitchScope.SPECIALTY,
    KillSwitchScope.WORKFLOW,
    KillSwitchScope.PROTOCOL,
    KillSwitchScope.CLINICIAN,
    KillSwitchScope.MODEL_PROVIDER,
    KillSwitchScope.INTEGRATION,
    KillSwitchScope.COMMUNICATION_CHANNEL,
)


@dataclass(frozen=True)
class KillSwitch:
    """One active suppression. ``target`` is the identifier within the scope.

    ``GLOBAL`` ignores ``target`` (it covers everything); every other scope matches only its
    named target (e.g. scope=WORKFLOW target="results" suppresses the results workflow).
    ``reason`` and ``engaged_by`` are carried through to the decision for the audit trail.
    """

    scope: KillSwitchScope
    target: str = "*"
    reason: str = ""
    engaged_by: str = ""


@dataclass(frozen=True)
class AutomationAttempt:
    """The attributes of one automation attempt, matched against active switches.

    Any field left ``None`` means "not attributed": a switch at that scope still matches it
    (deny-on-ambiguity), because we cannot prove the attempt falls outside the switch.
    """

    tenant_id: str | None = None
    site: str | None = None
    specialty: str | None = None
    workflow: str | None = None
    protocol: str | None = None
    clinician: str | None = None
    model_provider: str | None = None
    integration: str | None = None
    communication_channel: str | None = None


@dataclass(frozen=True)
class KillSwitchDecision:
    suppressed: bool
    scope: KillSwitchScope | None = None
    target: str | None = None
    reason: str = ""
    engaged_by: str = ""
    # Every active switch that matched, broadest-first — the full picture for operators.
    matched: tuple[KillSwitch, ...] = field(default_factory=tuple)

    @property
    def allowed(self) -> bool:
        return not self.suppressed


def _attempt_value(attempt: AutomationAttempt, scope: KillSwitchScope) -> str | None:
    return {
        KillSwitchScope.GLOBAL: "*",
        KillSwitchScope.TENANT: attempt.tenant_id,
        KillSwitchScope.SITE: attempt.site,
        KillSwitchScope.SPECIALTY: attempt.specialty,
        KillSwitchScope.WORKFLOW: attempt.workflow,
        KillSwitchScope.PROTOCOL: attempt.protocol,
        KillSwitchScope.CLINICIAN: attempt.clinician,
        KillSwitchScope.MODEL_PROVIDER: attempt.model_provider,
        KillSwitchScope.INTEGRATION: attempt.integration,
        KillSwitchScope.COMMUNICATION_CHANNEL: attempt.communication_channel,
    }[scope]


def _matches(switch: KillSwitch, attempt: AutomationAttempt) -> bool:
    """Does ``switch`` cover ``attempt``?

    GLOBAL always matches. A wildcard target ("*") matches the whole scope. Otherwise the
    switch matches when the attempt's value at that scope equals the target — OR when the
    attempt did not attribute that scope at all (``None``), which is the deny-on-ambiguity
    rule: an unattributed attempt cannot be proven to fall outside the switch.
    """
    if switch.scope is KillSwitchScope.GLOBAL:
        return True
    value = _attempt_value(attempt, switch.scope)
    if switch.target == "*":
        return True
    if value is None:
        return True
    return value == switch.target


def resolve(
    attempt: AutomationAttempt, switches: list[KillSwitch]
) -> KillSwitchDecision:
    """Return whether automation is suppressed for ``attempt`` and the broadest cause.

    Pure and deterministic: the same inputs always yield the same decision, and the reported
    cause is the broadest active matching switch (GLOBAL before TENANT before …), so an
    operator sees the widest blast radius first.
    """
    matched = [s for s in switches if _matches(s, attempt)]
    if not matched:
        return KillSwitchDecision(suppressed=False)

    order = {scope: i for i, scope in enumerate(SCOPE_PRECEDENCE)}
    matched.sort(key=lambda s: order[s.scope])
    cause = matched[0]
    return KillSwitchDecision(
        suppressed=True,
        scope=cause.scope,
        target=cause.target,
        reason=cause.reason,
        engaged_by=cause.engaged_by,
        matched=tuple(matched),
    )


def llm_provider_suppressed(provider: str, switches: list[KillSwitch]) -> bool:
    """Convenience: is a specific LLM/model provider killed?

    Used by the provider-failover chain (``reliability.core``) so a provider under a
    MODEL_PROVIDER (or GLOBAL) kill switch is skipped, satisfying the GA requirement to
    validate the LLM kill switch across all scopes.
    """
    decision = resolve(AutomationAttempt(model_provider=provider), switches)
    return decision.suppressed
