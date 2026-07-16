"""Specialty Protocol Breadth service interface (spec §7.4; plan Phase 10 — closes G6).

The public entry point for the specialty registry, the validated pack library, and — the
governed core of this phase — **per-tenant threshold customization with no code change**.

Governance guarantees enforced here:

  * **A customization can never weaken safety.** ``set_threshold`` re-validates the whole pack
    with the proposed override (bind → parse → ``assert_cannot_weaken_safety`` → required test
    cases) BEFORE persisting. An override that would down-classify a critical value, break a
    required test, or name an undeclared parameter is rejected — the practice gets an explicit
    error, not a silently-unsafe live rule. This is the same activation gate the Rule Studio
    enforces, applied to threshold data.
  * **Every change is audited + event-published.** The before/after value, actor, and pack
    version are recorded so a decision is always traceable to the policy that produced it.
  * **Resolution is deterministic and tenant-scoped.** ``resolve_rules`` composes the global
    base rules with each specialty pack bound to the resolving tenant's effective thresholds —
    the exact rule set the engine evaluates, replayable from the stored snapshot + policy.

The pure pack mechanics live in ``core`` (Django-free, exhaustively unit-tested); this module
only adds persistence, audit, events, and the tenant binding.
"""
from __future__ import annotations

import uuid
from functools import lru_cache
from typing import Any

from clinara_protocol_engine import Rule, load_rules
from clinara_shared_types import EventType
from django.conf import settings
from django.db import transaction

from clinara.middleware.phi_safe_logging import correlation_id as _correlation_id
from clinara.middleware.tenant import current_tenant_id, set_db_tenant
from core.outbox import publish_event
from domains.audit import services as audit

from . import core
from .catalog import AMBULATORY_SPECIALTIES, specialty_keys
from .models import SpecialtyThresholdPolicy


class UnknownSpecialty(LookupError):
    """No pack (or registry entry) exists for the requested specialty."""


class ThresholdRejected(ValueError):
    """A proposed threshold override fails the pack activation gate (unsafe / breaks a test)."""


def _bind(tenant_id: str) -> None:
    current_tenant_id.set(str(tenant_id))
    if not _correlation_id.get():
        _correlation_id.set(str(uuid.uuid4()))
    set_db_tenant(str(tenant_id))


# --------------------------------------------------------------------------------------
# Pack library (loaded once; content is code-reviewed data on disk)
# --------------------------------------------------------------------------------------

@lru_cache(maxsize=1)
def _packs() -> tuple[core.SpecialtyPack, ...]:
    return tuple(core.load_packs(settings.CLINICAL_SPECIALTY_PACKS_DIR))


@lru_cache(maxsize=1)
def _base_rules() -> tuple[Rule, ...]:
    """The Phase 1 global base rules (flat ``clinical/protocols/*.yaml``), unchanged."""
    return tuple(load_rules(settings.CLINICAL_RULES_DIR))


def packs() -> list[core.SpecialtyPack]:
    return list(_packs())


def pack_for_specialty(specialty: str) -> core.SpecialtyPack:
    for pack in _packs():
        if pack.specialty == specialty:
            return pack
    raise UnknownSpecialty(f"no specialty pack keyed {specialty!r}")


def list_specialties() -> list[dict[str, Any]]:
    """The registry, annotated with pack coverage (for the API / admin surface)."""
    cov = core.coverage(list(_packs()), specialty_keys())
    out = []
    for key, spec in AMBULATORY_SPECIALTIES.items():
        out.append({
            "key": key, "display_name": spec.display_name, "panels": list(spec.panels),
            "covered": cov.get(key, False),
        })
    return out


def validate_all() -> list[core.PackValidation]:
    """Validate every pack (used by tests + a release-gate check)."""
    return [core.validate_pack(p) for p in _packs()]


def coverage_report() -> dict[str, Any]:
    packs_ = list(_packs())
    keys = specialty_keys()
    uncovered = core.uncovered(packs_, keys)
    return {
        "registered": len(keys),
        "covered": len(keys) - len(uncovered),
        "uncovered": uncovered,
        "packs": len(packs_),
    }


# --------------------------------------------------------------------------------------
# Per-tenant threshold customization (the "no code change" seam)
# --------------------------------------------------------------------------------------

def get_overrides(tenant_id: str, specialty: str) -> dict[str, Any]:
    _bind(tenant_id)
    policy = SpecialtyThresholdPolicy.objects.filter(
        tenant_id=tenant_id, specialty=specialty
    ).first()
    return dict(policy.overrides) if policy else {}


def effective_thresholds(tenant_id: str, specialty: str) -> dict[str, Any]:
    """Pack defaults overlaid with the tenant's overrides — the values the engine will use."""
    pack = pack_for_specialty(specialty)
    return core.resolve_parameters(pack, get_overrides(tenant_id, specialty))


def set_threshold(
    *, tenant_id: str, specialty: str, parameter: str, value: Any, actor: str = "system",
) -> SpecialtyThresholdPolicy:
    """Override one pack threshold for a practice. Rejects anything that fails the gate.

    The whole pack is re-validated with the proposed override before it is stored, so a
    customization can never down-classify a critical value or break a required test case. On
    success the change is audited, event-published, and the policy version is bumped.
    """
    _bind(tenant_id)
    pack = pack_for_specialty(specialty)
    if parameter not in pack.parameters:
        raise ThresholdRejected(
            f"{parameter!r} is not a declared parameter of the {specialty!r} pack"
        )

    current = get_overrides(tenant_id, specialty)
    proposed = {**current, parameter: value}

    validation = core.validate_pack(pack, proposed)
    if not validation.ok:
        raise ThresholdRejected(
            f"override {parameter}={value!r} fails the {specialty!r} pack gate: "
            f"{validation.errors}"
        )

    before = current.get(parameter, pack.parameters[parameter])
    with transaction.atomic():
        policy, created = SpecialtyThresholdPolicy.objects.select_for_update().get_or_create(
            tenant_id=tenant_id, specialty=specialty,
            defaults={"overrides": proposed, "updated_by": actor},
        )
        if not created:
            policy.overrides = proposed
            policy.updated_by = actor
            policy.version = policy.version + 1
            policy.save(update_fields=["overrides", "updated_by", "version", "updated_at"])
        audit.record(
            actor=actor, action="specialty_threshold_updated",
            resource=f"specialty_threshold:{specialty}", reason=parameter,
            before_state={"parameter": parameter, "value": before},
            after_state={"parameter": parameter, "value": value, "version": policy.version},
        )
        publish_event(
            event_type=EventType.SPECIALTY_THRESHOLD_UPDATED.value,
            idempotency_key=f"specialty-threshold:{tenant_id}:{specialty}:{parameter}:"
                            f"{policy.version}",
            payload={"specialty": specialty, "parameter": parameter, "value": value,
                     "version": policy.version, "actor": actor},
        )
    return policy


def reset_thresholds(
    *, tenant_id: str, specialty: str, actor: str = "system",
) -> SpecialtyThresholdPolicy | None:
    """Clear a practice's overrides back to pack defaults (audited)."""
    _bind(tenant_id)
    pack_for_specialty(specialty)  # validates the specialty exists
    with transaction.atomic():
        policy = SpecialtyThresholdPolicy.objects.select_for_update().filter(
            tenant_id=tenant_id, specialty=specialty
        ).first()
        if policy is None:
            return None
        before = dict(policy.overrides)
        policy.overrides = {}
        policy.updated_by = actor
        policy.version = policy.version + 1
        policy.save(update_fields=["overrides", "updated_by", "version", "updated_at"])
        audit.record(
            actor=actor, action="specialty_threshold_reset",
            resource=f"specialty_threshold:{specialty}", reason="reset_to_defaults",
            before_state={"overrides": before}, after_state={"version": policy.version},
        )
        publish_event(
            event_type=EventType.SPECIALTY_THRESHOLD_RESET.value,
            idempotency_key=f"specialty-threshold-reset:{tenant_id}:{specialty}:"
                            f"{policy.version}",
            payload={"specialty": specialty, "version": policy.version, "actor": actor},
        )
    return policy


# --------------------------------------------------------------------------------------
# Rule resolution — the composed rule set the engine evaluates for a tenant
# --------------------------------------------------------------------------------------

def resolve_rules(tenant_id: str, specialty: str | None = None) -> list[Rule]:
    """Base rules + every specialty pack bound to this tenant's effective thresholds.

    Deterministic and tenant-scoped. The engine filters the returned set by marker and
    ``scope.specialties``, so passing the incoming ``specialty`` is not required here — the
    full bound set is returned and the engine selects. Per-tenant threshold overrides enter
    ONLY through ``bind_parameters``; no rule YAML is mutated (plan Phase 10: no code change).
    """
    _bind(tenant_id)
    rules: list[Rule] = list(_base_rules())
    # One policy lookup per pack specialty; small, cached content, cheap binding.
    overrides_by_specialty = {
        p.specialty: get_overrides(tenant_id, p.specialty) for p in _packs()
    }
    for pack in _packs():
        rules.extend(core.pack_rules(pack, overrides_by_specialty.get(pack.specialty)))
    return rules
