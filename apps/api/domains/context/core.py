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


def build_context_panel(*, facts: dict, provenance: dict) -> dict:
    """Project a stored snapshot into the clinician-facing chart-context panel (plan Phase 8 —
    closes G5). Pure and presentation-only: it re-groups the flat, provenance-tracked snapshot
    facts into the labs / patient-context / provenance a clinician needs beside the item under
    review, so no chart digging is required. It never adds facts or makes a clinical judgement
    — every value shown is drawn verbatim from the snapshot the engine already reasoned over.

    Returns ``{"labs", "patient_context", "specialty", "provenance"}`` where each lab carries
    its value, unit, reference range, trend, prior value, and an in/below/above-range status
    computed purely from the range already in the snapshot.
    """
    labs: list[dict] = []
    lab = _lab_from_facts(facts)
    if lab is not None:
        labs.append(lab)

    patient_context = {
        key[len("patient."):]: value
        for key, value in facts.items()
        if key.startswith("patient.")
    }

    freshness = provenance.get("data_freshness_seconds", {}) or {}
    panel_provenance = {
        "source_record_ids": provenance.get("source_record_ids", []),
        "freshness_seconds": freshness,
        "freshest_source_seconds": min(freshness.values()) if freshness else None,
        "missing_facts": provenance.get("missing_facts", []),
        "conflicting_facts": provenance.get("conflicting_facts", []),
        "transformations": provenance.get("transformations", []),
        "terminology_mappings": provenance.get("terminology_mappings", {}),
        "builder_version": provenance.get("context_builder_version", ""),
    }
    return {
        "labs": labs,
        "patient_context": patient_context,
        "specialty": facts.get("context.specialty"),
        "provenance": panel_provenance,
    }


def _lab_from_facts(facts: dict) -> dict | None:
    """Extract the single lab result carried in a results snapshot, or ``None`` if absent."""
    if facts.get("lab.marker") is None or facts.get("lab.value") is None:
        return None
    value = facts.get("lab.value")
    ref_low = facts.get("lab.ref_low")
    ref_high = facts.get("lab.ref_high")
    return {
        "marker": facts.get("lab.marker"),
        "value": value,
        "unit": facts.get("lab.unit"),
        "reference_range": {"low": ref_low, "high": ref_high},
        "prior_value": facts.get("lab.prior_value"),
        "trend": facts.get("lab.trend"),
        "status": _range_status(value, ref_low, ref_high),
    }


def _range_status(value, ref_low, ref_high) -> str:
    """in_range / below_range / above_range / unknown — purely from the snapshot's own range."""
    if value is None or (ref_low is None and ref_high is None):
        return "unknown"
    if ref_low is not None and value < ref_low:
        return "below_range"
    if ref_high is not None and value > ref_high:
        return "above_range"
    return "in_range"
