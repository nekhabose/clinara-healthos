"""Immutable context snapshot builder (plan Phase 1, workstream 4 — spec §8.3).

Runs with PYTHONPATH=apps/api.
"""
from datetime import datetime, timedelta, timezone

from domains.clinical_data.core import canonicalize
from domains.context.core import build_snapshot, snapshot_hash

NOW = datetime(2026, 7, 14, 12, 0, tzinfo=timezone.utc)


def test_snapshot_records_facts_and_provenance():
    obs = canonicalize(system="LOINC", code="4548-4", value=7.8, unit="%",
                       observed_at=NOW - timedelta(hours=2))
    snap = build_snapshot(
        tenant_id="t", patient_id="p", observation=obs, now=NOW,
        patient_facts={"patient.has_diabetes": True}, prior_value=7.1,
        source_record_ids=["obs-1"],
    )
    assert snap.facts["lab.a1c"] == 7.8
    assert snap.facts["lab.trend"] == "rising"
    assert snap.facts["patient.has_diabetes"] is True
    assert snap.provenance.source_record_ids == ["obs-1"]
    assert snap.provenance.data_freshness_seconds["observation"] == 7200
    assert snap.provenance.terminology_mappings == {"LOINC:4548-4": "hemoglobin_a1c"}


def test_unit_conversion_is_recorded_as_a_transformation():
    obs = canonicalize(system="LOINC", code="2345-7", value=5.0, unit="mmol/L", observed_at=NOW)
    snap = build_snapshot(tenant_id="t", patient_id="p", observation=obs, now=NOW)
    assert any("unit_normalized" in t for t in snap.provenance.transformations)
    assert round(snap.facts["lab.value"], 1) == 90.1


def test_unsupported_unit_marks_supported_false_and_omits_value():
    obs = canonicalize(system="LOINC", code="2345-7", value=5.0, unit="g/L", observed_at=NOW)
    snap = build_snapshot(tenant_id="t", patient_id="p", observation=obs, now=NOW)
    assert snap.facts["lab.supported"] is False
    assert "lab.a1c" not in snap.facts
    assert "lab.glucose" in snap.provenance.missing_facts


def test_snapshot_is_immutable_and_hashable_for_replay():
    obs = canonicalize(system="LOINC", code="2823-3", value=4.2, unit="mmol/L", observed_at=NOW)
    snap = build_snapshot(tenant_id="t", patient_id="p", observation=obs, now=NOW)
    h1 = snapshot_hash(snap)
    h2 = snapshot_hash(snap)
    assert h1 == h2  # stable content hash
    # Frozen pydantic model: mutation is rejected.
    import pydantic
    try:
        snap.facts = {}
        assert False, "snapshot should be immutable"
    except pydantic.ValidationError:
        pass
