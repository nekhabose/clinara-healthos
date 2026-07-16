"""Compliance service interface (spec §10.1, §7.4).

Collects evidence counts from the audit/workflow tables, runs the pure attestation core, and
persists a hash-stamped ``AttestationRecord``. In this build the collection helper accepts the
counts explicitly (the caller queries the relevant tables); the value is the deterministic,
all-or-nothing attestation and its tamper-evident digest.
"""
from __future__ import annotations

from clinara_shared_types import EventType
from django.db import transaction

from core.outbox import publish_event
from domains.audit import services as audit

from .core import AttestationReport, EvidenceInput, build_attestation
from .models import AttestationRecord


@transaction.atomic
def generate_attestation(evidence: EvidenceInput, *, window_label: str) -> AttestationRecord:
    """Build and persist an attestation for a window. Audited + event-published."""
    report: AttestationReport = build_attestation(evidence)
    record = AttestationRecord.objects.create(
        window_label=window_label,
        frameworks=list(report.frameworks),
        attested=report.attested,
        evidence_digest=report.evidence_digest,
        controls=[
            {"key": c.key, "total": c.total, "covered": c.covered, "passed": c.passed}
            for c in report.controls
        ],
        gaps=list(report.gaps),
    )
    audit.record(
        actor="system",
        action="compliance.attest",
        resource=f"attestation:{record.id}",
        reason=window_label,
        after_state={"attested": report.attested, "digest": report.evidence_digest},
    )
    publish_event(
        event_type=EventType.ATTESTATION_GENERATED.value,
        idempotency_key=f"attestation-{record.id}",
        payload={
            "window": window_label,
            "attested": report.attested,
            "digest": report.evidence_digest,
            "gaps": list(report.gaps),
        },
    )
    return record


__all__ = ["generate_attestation", "build_attestation", "EvidenceInput"]
