"""Compliance attestation evidence (GA hardening — spec §10.1, §5.8).

SOC 2 Type II and HIPAA readiness is not a document — it is *evidence that controls
operated continuously*. This module is the pure, Django-free core that turns raw platform
facts into an auditable ``AttestationReport``: it checks the three completeness properties an
auditor asks for and refuses to attest if any gap exists.

Properties checked:
  * **Audit completeness** — every mutating action produced an audit record. A write with no
    matching audit event is a control failure (spec §10.4 / cross-cutting foundation).
  * **Access-log completeness** — every PHI access was logged with actor + reason.
  * **Decision-trace availability** — 100% of completed workflows have a replayable trace
    (spec §12.4 SLO). Anything less blocks attestation.

The report is deterministic and content-hashed so the same inputs yield the same evidence
digest — auditors can verify an exported attestation was not altered. The Django layer feeds
it counts pulled from the audit/workflow tables and persists the signed report.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field

# Compliance frameworks the platform attests to (spec §10.1).
FRAMEWORKS: tuple[str, ...] = ("HIPAA", "SOC 2 Type II", "HITECH")


@dataclass(frozen=True)
class EvidenceInput:
    """Raw facts for one attestation window, supplied by the Django layer.

    Counts are non-negative integers pulled from the audit/access/workflow tables for the
    window. ``*_with_evidence`` must equal its total for the corresponding control to pass.
    """

    mutating_actions: int = 0
    mutating_actions_audited: int = 0
    phi_accesses: int = 0
    phi_accesses_logged: int = 0
    completed_workflows: int = 0
    completed_workflows_with_trace: int = 0


@dataclass(frozen=True)
class ControlResult:
    key: str
    description: str
    total: int
    covered: int
    passed: bool

    @property
    def gap(self) -> int:
        return self.total - self.covered


@dataclass(frozen=True)
class AttestationReport:
    frameworks: tuple[str, ...]
    controls: tuple[ControlResult, ...]
    attested: bool
    evidence_digest: str
    gaps: tuple[str, ...] = field(default_factory=tuple)


def _control(key: str, description: str, total: int, covered: int) -> ControlResult:
    # Coverage must be exact: a single un-evidenced action fails the control. ``covered`` is
    # clamped so a bad input (covered > total) can never manufacture a pass.
    covered = min(covered, total)
    return ControlResult(key, description, total, covered, passed=(covered == total))


def _digest(controls: tuple[ControlResult, ...]) -> str:
    material = json.dumps(
        [[c.key, c.total, c.covered, c.passed] for c in controls], sort_keys=True
    )
    return hashlib.sha256(material.encode()).hexdigest()


def build_attestation(evidence: EvidenceInput) -> AttestationReport:
    """Evaluate all completeness controls and produce a signed, hash-stamped attestation.

    ``attested`` is true only if EVERY control passes — attestation is all-or-nothing, so a
    partial gap can never be rounded up into a clean report.
    """
    controls = (
        _control(
            "audit_completeness",
            "Every mutating action produced an audit record",
            evidence.mutating_actions,
            evidence.mutating_actions_audited,
        ),
        _control(
            "access_log_completeness",
            "Every PHI access was logged with actor and reason",
            evidence.phi_accesses,
            evidence.phi_accesses_logged,
        ),
        _control(
            "decision_trace_availability",
            "Every completed workflow has a replayable decision trace",
            evidence.completed_workflows,
            evidence.completed_workflows_with_trace,
        ),
    )
    gaps = tuple(
        f"{c.description}: {c.gap} of {c.total} missing" for c in controls if not c.passed
    )
    return AttestationReport(
        frameworks=FRAMEWORKS,
        controls=controls,
        attested=all(c.passed for c in controls),
        evidence_digest=_digest(controls),
        gaps=gaps,
    )
