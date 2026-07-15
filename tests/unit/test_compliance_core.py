"""Compliance attestation core (GA hardening — spec §10.1).

Django-free; runs with PYTHONPATH=apps/api. Attestation is all-or-nothing: any completeness
gap blocks it.
"""
from domains.compliance import core


def _complete(n=100):
    return core.EvidenceInput(
        mutating_actions=n,
        mutating_actions_audited=n,
        phi_accesses=n,
        phi_accesses_logged=n,
        completed_workflows=n,
        completed_workflows_with_trace=n,
    )


def test_complete_evidence_attests():
    report = core.build_attestation(_complete())
    assert report.attested is True
    assert report.gaps == ()
    assert report.frameworks == ("HIPAA", "SOC 2 Type II", "HITECH")
    assert all(c.passed for c in report.controls)


def test_missing_audit_record_blocks_attestation():
    ev = _complete()
    ev = core.EvidenceInput(
        mutating_actions=100,
        mutating_actions_audited=99,  # one write without an audit record
        phi_accesses=100,
        phi_accesses_logged=100,
        completed_workflows=100,
        completed_workflows_with_trace=100,
    )
    report = core.build_attestation(ev)
    assert report.attested is False
    assert any("audit record" in g for g in report.gaps)


def test_missing_access_log_blocks_attestation():
    ev = core.EvidenceInput(
        mutating_actions=10,
        mutating_actions_audited=10,
        phi_accesses=10,
        phi_accesses_logged=8,
        completed_workflows=10,
        completed_workflows_with_trace=10,
    )
    report = core.build_attestation(ev)
    assert report.attested is False
    assert any("PHI access" in g for g in report.gaps)


def test_decision_trace_gap_blocks_attestation():
    ev = core.EvidenceInput(
        mutating_actions=10,
        mutating_actions_audited=10,
        phi_accesses=10,
        phi_accesses_logged=10,
        completed_workflows=10,
        completed_workflows_with_trace=9,
    )
    report = core.build_attestation(ev)
    assert report.attested is False
    assert any("decision trace" in g for g in report.gaps)


def test_covered_cannot_exceed_total():
    # A malformed input claiming more coverage than actions must not manufacture a pass by
    # itself — but here totals are honest, so it still passes; the clamp guards the ratio.
    ev = core.EvidenceInput(
        mutating_actions=5,
        mutating_actions_audited=99,  # clamped to 5
        phi_accesses=5,
        phi_accesses_logged=5,
        completed_workflows=5,
        completed_workflows_with_trace=5,
    )
    report = core.build_attestation(ev)
    audit_control = next(c for c in report.controls if c.key == "audit_completeness")
    assert audit_control.covered == 5


def test_zero_activity_attests_vacuously():
    # No actions in the window ⇒ no gaps ⇒ controls hold (0 of 0 covered).
    report = core.build_attestation(core.EvidenceInput())
    assert report.attested is True


def test_evidence_digest_is_deterministic():
    a = core.build_attestation(_complete())
    b = core.build_attestation(_complete())
    assert a.evidence_digest == b.evidence_digest
    assert len(a.evidence_digest) == 64  # sha256 hex


def test_evidence_digest_changes_with_evidence():
    a = core.build_attestation(_complete(100))
    b = core.build_attestation(_complete(101))
    assert a.evidence_digest != b.evidence_digest
