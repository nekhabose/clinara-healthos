# Compliance (GA hardening — spec §10.1)

Turns raw platform facts into auditable, tamper-evident attestation evidence for HIPAA / SOC 2
Type II / HITECH readiness.

| File | Responsibility |
|---|---|
| `core.py` | Pure: `build_attestation(evidence) -> AttestationReport`. Checks audit completeness, access-log completeness, and decision-trace availability; attestation is all-or-nothing and hash-stamped. Unit-tested in `tests/unit/test_compliance_core.py`. |
| `models.py` | `AttestationRecord` — persisted, digest-stamped attestations for auditor export. |
| `services.py` | `generate_attestation(evidence, window_label)` — build, persist, audit, publish `AttestationGenerated`. |

**Controls checked**
- **Audit completeness** — every mutating action produced an audit record.
- **Access-log completeness** — every PHI access was logged with actor + reason.
- **Decision-trace availability** — 100% of completed workflows have a replayable trace (§12.4).

A single gap blocks attestation — a partial gap is never rounded up to a clean report. See
`docs/compliance/` for the framework control mapping (HIPAA/SOC 2/BAA).
