# Monitoring & Observability

OpenTelemetry-based (spec §7.2, §12). Traces/metrics from the api + workers flow through
the collector (`otel-collector.yaml`) with PHI-scrubbing before export to Datadog/CloudWatch.

## Signals to wire per phase (spec §12)

- **Technical:** request latency, error rate, queue depth, worker health, event processing
  latency, retry/dead-letter rate, API availability.
- **Clinical workflow:** no-match / multiple-match / missing-context / unknown-marker /
  unit-mismatch / automation-suppression rates, clinician agreement/edit/override, critical
  escalation latency, delivery + write-back failures.
- **Critical alerts:** interface disconnected, critical event delayed, silent event gap,
  write-back spike, unknown-mapping spike, rule conflict, patient-identity mismatch,
  cross-tenant access attempt, LLM validation-failure spike.

## SLOs (spec §12.4)

99.9% ingestion availability · 99% routine < 2 min · 99% critical < 30 s · zero silent
message loss · 99.9% audit-write success · 100% decision-trace availability.
