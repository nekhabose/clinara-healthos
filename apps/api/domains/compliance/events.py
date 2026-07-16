"""Domain events published by the Compliance module.

Generating an attestation publishes ``AttestationGenerated`` so the evidence pipeline and the
release gate (compliance readiness) can consume it.
"""
