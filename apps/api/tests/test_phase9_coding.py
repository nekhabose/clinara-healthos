"""Phase 9 — Billing & Coding Intelligence (closes G1).

Two layers: the pure deterministic detectors (no DB) and the governed service layer
(review queue, human-in-the-loop confirmation, export gate, audit, events, analytics hook,
tenant isolation). The through-line is the invariant from ``gaps.md §1``: every suggestion
is deterministic + evidence-linked, and nothing is ever auto-applied to a claim.
"""
import uuid

import pytest

from domains.coding import core, services
from domains.coding.core import EncounterDiagnosis as Dx
from domains.coding.core import ProblemListItem as Problem
from domains.coding.core import SuggestionType
from domains.coding.models import CodingSuggestionRecord, SuggestionStatus

# --------------------------------------------------------------------------------------
# Pure detectors — no DB
# --------------------------------------------------------------------------------------


def test_documented_uncoded_flags_active_problem_absent_from_encounter():
    out = core.detect_documented_uncoded(
        [Problem(description="Type 2 diabetes mellitus", code="E11.9", status="active")],
        [Dx(code="I10", description="Hypertension")],
    )
    assert len(out) == 1
    assert out[0].suggestion_type is SuggestionType.DOCUMENTED_UNCODED
    assert out[0].icd10_code == "E11.9"
    assert out[0].evidence  # never empty


def test_documented_uncoded_is_silent_when_already_coded_or_inactive():
    already = core.detect_documented_uncoded(
        [Problem(description="Diabetes", code="E11.9", status="active")],
        [Dx(code="E11.9")],
    )
    resolved = core.detect_documented_uncoded(
        [Problem(description="Diabetes", code="E11.9", status="resolved")], [],
    )
    no_code = core.detect_documented_uncoded(
        [Problem(description="Diabetes", code=None, status="active")], [],
    )
    assert already == [] and resolved == [] and no_code == []


def test_hcc_gap_diabetes_from_a1c_only_above_threshold():
    hit = core.detect_hcc_gaps({core.catalog.MARKER_A1C: 7.2}, [], [])
    assert [s.icd10_code for s in hit] == ["E11.9"]
    assert hit[0].suggestion_type is SuggestionType.HCC_GAP
    assert hit[0].requires_provider_confirmation is True
    assert hit[0].hcc  # risk-adjustable tag present

    # Below the diagnostic threshold → nothing (anti-upcoding floor).
    assert core.detect_hcc_gaps({core.catalog.MARKER_A1C: 6.0}, [], []) == []


def test_hcc_gap_diabetes_suppressed_when_already_documented():
    assert core.detect_hcc_gaps(
        {core.catalog.MARKER_A1C: 8.0},
        [Problem(description="Type 2 diabetes", code="E11.9")], [],
    ) == []


def test_hcc_gap_ckd_from_low_egfr_and_negative_above_floor():
    hit = core.detect_hcc_gaps({core.catalog.MARKER_EGFR: 25.0}, [], [])
    assert [s.icd10_code for s in hit] == ["N18.4"]  # stage 4
    assert hit[0].hcc

    # eGFR at/above 60 → no CKD suggestion at all.
    assert core.detect_hcc_gaps({core.catalog.MARKER_EGFR: 72.0}, [], []) == []


def test_specificity_upgrade_stages_unspecified_ckd():
    out = core.detect_specificity_upgrades({core.catalog.MARKER_EGFR: 40.0}, [Dx(code="N18.9")])
    assert len(out) == 1
    assert out[0].suggestion_type is SuggestionType.SPECIFICITY_UPGRADE
    assert out[0].icd10_code == "N18.32"  # 30-45 band
    assert out[0].supersedes_code == "N18.9"


def test_specificity_upgrade_diabetes_with_ckd_complication():
    out = core.detect_specificity_upgrades({core.catalog.MARKER_EGFR: 40.0}, [Dx(code="E11.9")])
    assert any(s.icd10_code == "E11.22" and s.supersedes_code == "E11.9" for s in out)


def test_specificity_upgrade_silent_without_the_unspecified_code():
    # eGFR present but the encounter has no unspecified code to sharpen.
    out = core.detect_specificity_upgrades({core.catalog.MARKER_EGFR: 40.0}, [Dx(code="I10")])
    assert out == []


def test_analyze_is_deterministic_evidence_linked_and_empty_on_no_signal():
    empty = core.analyze(facts={}, problem_list=[], encounter_dx=[])
    assert empty.suggestions == ()

    a = core.analyze(lab_values={core.catalog.MARKER_EGFR: 25.0}, encounter_dx=[Dx(code="N18.9")])
    b = core.analyze(lab_values={core.catalog.MARKER_EGFR: 25.0}, encounter_dx=[Dx(code="N18.9")])
    assert a.as_dict() == b.as_dict()  # deterministic
    assert all(s.evidence for s in a.suggestions)  # every suggestion evidence-linked


def test_analyze_reads_single_lab_from_snapshot_facts():
    facts = {"lab.marker": core.catalog.MARKER_EGFR, "lab.value": 25.0}
    result = core.analyze(facts=facts, problem_list=[], encounter_dx=[])
    assert any(s.icd10_code == "N18.4" for s in result.suggestions)


# --------------------------------------------------------------------------------------
# Governed service layer — DB
# --------------------------------------------------------------------------------------

pytestmark = pytest.mark.django_db


def _tenant() -> str:
    return str(uuid.uuid4())


def _analyze(tenant, **kw):
    return services.analyze_encounter(
        tenant_id=tenant, patient_external_id=kw.get("patient", "pat-1"),
        lab_values=kw.get("lab_values", {core.catalog.MARKER_EGFR: 25.0}),
        problem_list=kw.get("problem_list", []),
        encounter_dx=kw.get("encounter_dx", []),
        encounter_id=kw.get("encounter_id", "enc-1"),
    )


def test_analyze_creates_pending_queue_nothing_auto_applied():
    t = _tenant()
    recs = _analyze(t)
    assert recs, "expected at least one suggestion"
    # No suggestion is ever created in an applied/confirmed state.
    assert all(r.status == SuggestionStatus.PENDING for r in recs)
    assert not CodingSuggestionRecord.objects.filter(
        tenant_id=t, status__in=[SuggestionStatus.CONFIRMED, SuggestionStatus.EXPORTED]
    ).exists()


def test_analyze_is_idempotent_per_gap():
    t = _tenant()
    first = _analyze(t)
    second = _analyze(t)
    assert len(first) == len(second)
    assert CodingSuggestionRecord.objects.filter(tenant_id=t).count() == len(first)


def test_confirm_advances_audits_and_feeds_analytics_loop():
    from core.models import DomainEventOutbox
    from domains.analytics import services as analytics
    from domains.audit.models import AuditEvent

    t = _tenant()
    rec = _analyze(t)[0]
    confirmed = services.confirm_suggestion(
        tenant_id=t, suggestion_id=str(rec.id), actor="dr-jones", reason="chart supports it"
    )
    assert confirmed.status == SuggestionStatus.CONFIRMED
    assert confirmed.decided_by == "dr-jones" and confirmed.decided_at is not None

    assert AuditEvent.objects.filter(
        tenant_id=t, action="coding_suggestion_confirmed").exists()
    assert DomainEventOutbox.objects.filter(
        tenant_id=t, event_type="CodingSuggestionConfirmed").exists()

    # Confirmation registered as a governed "coding" approval in the Phase 6 loop.
    board = analytics.dashboards(t)
    assert board["clinical"]["by_workflow_type"]["coding"]["approvals"] == 1


def test_reject_feeds_override_rate():
    from domains.analytics import services as analytics

    t = _tenant()
    rec = _analyze(t)[0]
    rejected = services.reject_suggestion(
        tenant_id=t, suggestion_id=str(rec.id), actor="dr-jones", reason="not clinically supported"
    )
    assert rejected.status == SuggestionStatus.REJECTED
    board = analytics.dashboards(t)
    assert board["clinical"]["by_workflow_type"]["coding"]["overrides"] == 1


def test_export_requires_confirmation_gate():
    t = _tenant()
    rec = _analyze(t)[0]

    # A pending suggestion can NEVER be exported.
    with pytest.raises(services.SuggestionStateError):
        services.export_suggestion(tenant_id=t, suggestion_id=str(rec.id), actor="coder")

    services.confirm_suggestion(tenant_id=t, suggestion_id=str(rec.id), actor="dr-jones")
    exported = services.export_suggestion(tenant_id=t, suggestion_id=str(rec.id), actor="coder")
    assert exported.status == SuggestionStatus.EXPORTED


def test_cannot_double_decide():
    t = _tenant()
    rec = _analyze(t)[0]
    services.confirm_suggestion(tenant_id=t, suggestion_id=str(rec.id), actor="dr-jones")
    with pytest.raises(services.SuggestionStateError):
        services.confirm_suggestion(tenant_id=t, suggestion_id=str(rec.id), actor="dr-jones")
    with pytest.raises(services.SuggestionStateError):
        services.reject_suggestion(tenant_id=t, suggestion_id=str(rec.id), actor="dr-jones")


def test_suggestions_are_tenant_isolated():
    t_a, t_b = _tenant(), _tenant()
    rec = _analyze(t_a)[0]
    assert services.list_suggestions(tenant_id=t_b) == []
    # A cross-tenant confirm cannot find the record.
    with pytest.raises(services.SuggestionNotFound):
        services.confirm_suggestion(tenant_id=t_b, suggestion_id=str(rec.id), actor="intruder")
    # Original tenant still has it, untouched.
    assert services.list_suggestions(tenant_id=t_a)[0].status == SuggestionStatus.PENDING


def test_analyze_from_snapshot_reads_the_immutable_context():
    from domains.context.models import ContextSnapshotRecord

    t = _tenant()
    wf = uuid.uuid4()
    ContextSnapshotRecord.objects.create(
        tenant_id=t, workflow_id=wf, patient_external_id="pat-77",
        snapshot_hash="deadbeef", builder_version="results-context-1",
        facts={"lab.marker": core.catalog.MARKER_EGFR, "lab.value": 25.0},
        provenance={},
    )
    recs = services.analyze_from_snapshot(tenant_id=t, workflow_id=str(wf), encounter_id="enc-9")
    assert any(r.icd10_code == "N18.4" for r in recs)
    assert recs[0].patient_external_id == "pat-77"
    assert recs[0].snapshot_hash == "deadbeef"


def test_analyze_from_snapshot_missing_snapshot_raises():
    t = _tenant()
    with pytest.raises(services.SuggestionNotFound):
        services.analyze_from_snapshot(tenant_id=t, workflow_id=str(uuid.uuid4()))
