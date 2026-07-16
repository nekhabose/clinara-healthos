# Compliance — Control Mapping & Attestation (spec §10.1, §5.8)

Clinara HealthOS attests to **HIPAA**, **SOC 2 Type II**, and **HITECH**. Attestation is not a
document — it is *evidence that controls operated continuously*. The `domains/compliance` module
turns raw platform facts into a hash-stamped, all-or-nothing `AttestationReport`; this doc maps
platform controls to the frameworks an auditor evaluates.

## Automated evidence (the three completeness controls)

The attestation core (`compliance.core.build_attestation`) refuses to attest unless **all** hold:

| Control | Evidence | Source of truth |
|---|---|---|
| **Audit completeness** | Every mutating action produced an audit record | hash-chained `AuditEvent` |
| **Access-log completeness** | Every PHI access logged with actor + reason | PHI-access audit + `PhiScrubFilter` |
| **Decision-trace availability** | 100% of completed workflows have a replayable trace | workflow decision traces (§12.4 SLO) |

A single gap blocks attestation — it is never rounded up. Each report carries a SHA-256
`evidence_digest` so an exported attestation can be proven un-altered.

## Framework mapping

| Requirement | HIPAA | SOC 2 | Where it lives |
|---|---|---|---|
| Access control / least privilege | §164.312(a) | CC6.1 | `domains/identity` RBAC, tenant RLS |
| Emergency access (break-glass) | §164.312(a)(2)(ii) | CC6.1 | `identity.breakglass` — time-boxed, audited |
| Audit controls | §164.312(b) | CC7.2 | hash-chained `AuditEvent`, audit-completeness control |
| Integrity / tamper evidence | §164.312(c) | CC7.1 | audit hash chain, attestation digest |
| Transmission security / encryption | §164.312(e) | CC6.7 | TLS in transit, KMS at rest (Terraform) |
| Availability / DR | §164.308(a)(7) | A1.2 | Multi-AZ + PITR (spec §15), quarterly drill |
| Incident response / kill switch | §164.308(a)(6) | CC7.4 | `domains/killswitch`, `SLOBreached` alerts |
| Change management / release gate | — | CC8.1 | `core/release_gate` (spec §13.5), Studio dual-approval |
| Monitoring / SLOs | — | CC7.2 | `domains/reliability`, spec §12.4 SLOs |

## Business Associate Agreements (BAAs)

- A signed BAA is required with every covered-entity customer and with every subprocessor that
  can touch PHI (cloud, model providers, delivery channels).
- **Model providers:** only providers under an executed BAA may be enabled. A provider without a
  current BAA must be kept behind a `MODEL_PROVIDER` kill switch so the failover chain skips it.

## Generating an attestation

```python
from domains.compliance import services as compliance
from domains.compliance.core import EvidenceInput

evidence = EvidenceInput(  # counts pulled from the audit/workflow tables for the window
    mutating_actions=..., mutating_actions_audited=...,
    phi_accesses=..., phi_accesses_logged=...,
    completed_workflows=..., completed_workflows_with_trace=...,
)
record = compliance.generate_attestation(evidence, window_label="2026-Q3")
# record.attested is True only if every control passed; record.evidence_digest is the seal.
```

The SOC 2 Type II readiness position is: controls are implemented **and** their continuous
operation is evidenced by the audit trail, SLO history, DR drill history, and periodic
attestations exported from this module.
