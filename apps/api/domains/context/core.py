"""Pure context-snapshot builder (plan Phase 1, workstream 4 — spec §8.3).

Produces the immutable ``ContextSnapshot`` the protocol engine evaluates. The snapshot
records not just facts but their provenance (sources, freshness, missing/conflicting
facts, transformations, mappings, builder version) so any decision is replayable
(plan §1.1 explainability). Django-free and deterministic.
"""
from __future__ import annotations

import hashlib
from datetime import datetime

from clinara_clinical_models import ContextProvenance, ContextSnapshot
from clinara_protocol_engine import LAB_FACT_ALIAS
from clinara_terminology import MARKER_SPECS

from domains.clinical_data.core import CanonicalObservation, compute_trend

CONTEXT_BUILDER_VERSION = "results-context-1"


def build_snapshot(
    *,
    tenant_id: str,
    patient_id: str,
    observation: CanonicalObservation,
    now: datetime,
    patient_facts: dict | None = None,
    prior_value: float | None = None,
    ref_low: float | None = None,
    ref_high: float | None = None,
    specialty: str | None = None,
    source_record_ids: list[str] | None = None,
    conflicting_facts: list[str] | None = None,
) -> ContextSnapshot:
    """Assemble the immutable snapshot for a single result evaluation.

    ``patient_facts`` carries context resolved elsewhere (e.g. ``patient.has_diabetes``
    from Condition resources). Effective reference range falls back to the marker default
    when the payload does not supply one — defaults never override critical thresholds.
    """
    facts: dict = dict(patient_facts or {})
    transformations: list[str] = []
    mappings: dict[str, str] = {}
    missing: list[str] = []

    facts["lab.supported"] = not observation.unsupported_unit
    if specialty:
        # Persisted so replay is fully self-contained (scope evaluation is reproducible).
        facts["context.specialty"] = specialty

    if observation.marker is not None:
        alias = LAB_FACT_ALIAS[observation.marker]
        spec = MARKER_SPECS[observation.marker]
        mappings[f"{observation.system}:{observation.code}"] = observation.marker.value

        if observation.unsupported_unit:
            missing.append(alias)
        else:
            facts[alias] = observation.value
            facts["lab.value"] = observation.value
            facts["lab.marker"] = observation.marker.value
            facts["lab.unit"] = observation.canonical_unit
            facts["lab.ref_low"] = ref_low if ref_low is not None else spec.ref_low
            facts["lab.ref_high"] = ref_high if ref_high is not None else spec.ref_high
            facts["lab.prior_value"] = prior_value
            facts["lab.trend"] = compute_trend(observation.value, prior_value)
            orig_unit = observation.original_unit
            if orig_unit and orig_unit != observation.canonical_unit:
                transformations.append(
                    f"unit_normalized:{orig_unit}->{observation.canonical_unit}"
                )
    else:
        missing.append("lab.value")

    provenance = ContextProvenance(
        source_record_ids=source_record_ids or [],
        source_timestamps={"observation": observation.observed_at},
        data_freshness_seconds={
            "observation": max(0, int((now - observation.observed_at).total_seconds()))
        },
        missing_facts=missing,
        conflicting_facts=conflicting_facts or [],
        transformations=transformations,
        terminology_mappings=mappings,
        context_builder_version=CONTEXT_BUILDER_VERSION,
    )
    return ContextSnapshot(
        tenant_id=tenant_id,
        patient_id=patient_id,
        facts=facts,
        provenance=provenance,
        context_created_at=now,
    )


def snapshot_hash(snapshot: ContextSnapshot) -> str:
    """Stable content hash for replay/audit (plan §1.1 — immutable, hashed snapshot)."""
    material = snapshot.model_dump_json()
    return hashlib.sha256(material.encode()).hexdigest()
