"""Integrations persistence (plan Phase 1 sandbox → Phase 3 hardened gateway).

Phase 1 stored the raw inbound payload BEFORE parsing and derived a stable idempotency key
so duplicate deliveries never double-process (spec §6.7.6). Phase 3 adds the production
gateway around it: per-interface `Integration` records, a `DeadLetterEvent` queue with
idempotent replay, `IntegrationError`/`Alert`/`Incident` for monitoring, per-source
rate-limit state, and silent-gap heartbeats — so a real HL7/FHIR feed survives duplicates,
malformed payloads, flaps, and outages with **zero silent loss** (plan §1.1 invariant 2).
"""
from __future__ import annotations

from django.db import models

from core.models import TenantScopedModel


class InboundStatus(models.TextChoices):
    RECEIVED = "received", "Received"
    PROCESSED = "processed", "Processed"
    FAILED = "failed", "Failed"
    DEAD_LETTERED = "dead_lettered", "Dead-lettered"


class IntegrationKind(models.TextChoices):
    FHIR = "fhir", "FHIR"
    HL7V2 = "hl7v2", "HL7 v2"


class IntegrationStatus(models.TextChoices):
    CONNECTED = "connected", "Connected"
    DEGRADED = "degraded", "Degraded"
    DISCONNECTED = "disconnected", "Disconnected"


class Integration(TenantScopedModel):
    """One production interface to an EHR/source (spec §6.7). Owns endpoints + credentials."""

    name = models.CharField(max_length=128)
    kind = models.CharField(max_length=16, choices=IntegrationKind.choices)
    source_system = models.CharField(max_length=128, blank=True, default="")
    status = models.CharField(
        max_length=16, choices=IntegrationStatus.choices,
        default=IntegrationStatus.CONNECTED, db_index=True,
    )
    # Silent-gap detection: how often this interface is expected to emit, and when last heard.
    expected_interval_seconds = models.PositiveIntegerField(default=0)  # 0 = no expectation
    last_seen_at = models.DateTimeField(null=True, blank=True)
    last_sequence = models.BigIntegerField(default=0)
    # Rate limiting (token bucket) config.
    rate_capacity = models.PositiveIntegerField(default=100)
    rate_refill_per_second = models.FloatField(default=50.0)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["tenant_id", "name"], name="uq_integration_tenant_name"
            )
        ]
        ordering = ["name"]

    def __str__(self) -> str:
        return f"integration:{self.name}[{self.status}]"


class IntegrationEndpoint(TenantScopedModel):
    integration = models.ForeignKey(
        Integration, on_delete=models.CASCADE, related_name="endpoints"
    )
    direction = models.CharField(max_length=8)  # inbound | outbound
    protocol = models.CharField(max_length=16)  # mllp | https
    address = models.CharField(max_length=255, blank=True, default="")

    def __str__(self) -> str:
        return f"endpoint:{self.direction}:{self.protocol}"


class IntegrationCredential(TenantScopedModel):
    """Credential POINTER only — the secret lives in a vault; we store its reference."""

    integration = models.ForeignKey(
        Integration, on_delete=models.CASCADE, related_name="credentials"
    )
    kind = models.CharField(max_length=32)          # e.g. smart_backend, mllp_tls
    secret_ref = models.CharField(max_length=255)   # vault key, never the raw secret

    def __str__(self) -> str:
        return f"credential:{self.kind}"


class RateLimitState(TenantScopedModel):
    """Persisted token-bucket state per (integration, source) — spec §6.7.4 rate limiting."""

    integration = models.ForeignKey(
        Integration, on_delete=models.CASCADE, related_name="rate_states"
    )
    source_key = models.CharField(max_length=128)
    tokens = models.FloatField(default=0.0)
    last_refill = models.FloatField(default=0.0)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["tenant_id", "integration", "source_key"], name="uq_rate_state"
            )
        ]

    def __str__(self) -> str:
        return f"rate:{self.source_key}:{self.tokens:.1f}"


class InboundMessage(TenantScopedModel):
    """Raw payload store — the durable record that nothing was silently dropped."""

    integration = models.ForeignKey(
        Integration, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="inbound_messages",
    )
    source = models.CharField(max_length=64)                 # e.g. "fhir-sandbox"
    message_type = models.CharField(max_length=64)           # e.g. "Observation"
    idempotency_key = models.CharField(max_length=200, unique=True)
    sequence = models.BigIntegerField(null=True, blank=True)
    raw_payload = models.JSONField()
    status = models.CharField(
        max_length=16, choices=InboundStatus.choices, default=InboundStatus.RECEIVED, db_index=True
    )
    error = models.TextField(blank=True, default="")

    class Meta:
        indexes = [models.Index(fields=["tenant_id", "status", "created_at"])]
        ordering = ["created_at"]

    def __str__(self) -> str:
        return f"{self.message_type}:{self.idempotency_key}[{self.status}]"


class DeadLetterStatus(models.TextChoices):
    OPEN = "open", "Open"
    REPLAYED = "replayed", "Replayed"
    DISCARDED = "discarded", "Discarded"


class DeadLetterEvent(TenantScopedModel):
    """A message that could not be processed — parked for inspect/replay (spec §6.7.4)."""

    integration = models.ForeignKey(
        Integration, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="dead_letters",
    )
    idempotency_key = models.CharField(max_length=200, blank=True, default="")
    raw = models.JSONField(default=dict)      # raw payload or {"hl7": "..."} — never dropped
    error = models.CharField(max_length=255)
    status = models.CharField(
        max_length=16, choices=DeadLetterStatus.choices,
        default=DeadLetterStatus.OPEN, db_index=True,
    )
    replay_count = models.PositiveIntegerField(default=0)

    class Meta:
        indexes = [models.Index(fields=["tenant_id", "status"])]
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"dead_letter:{self.error}[{self.status}]"


class IntegrationError(TenantScopedModel):
    integration = models.ForeignKey(
        Integration, on_delete=models.CASCADE, related_name="errors"
    )
    kind = models.CharField(max_length=48, db_index=True)  # malformed | duplicate | rate_limited …
    detail = models.CharField(max_length=255, blank=True, default="")

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"error:{self.kind}"


class AlertSeverity(models.TextChoices):
    INFO = "info", "Info"
    WARNING = "warning", "Warning"
    CRITICAL = "critical", "Critical"


class Alert(TenantScopedModel):
    """A monitoring alert on the critical set (spec §12.3) — e.g. interface disconnected,
    silent event gap, write-back failure spike."""

    integration = models.ForeignKey(
        Integration, on_delete=models.CASCADE, related_name="alerts"
    )
    kind = models.CharField(max_length=48, db_index=True)
    severity = models.CharField(max_length=12, choices=AlertSeverity.choices)
    message = models.CharField(max_length=255)
    resolved = models.BooleanField(default=False, db_index=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"alert:{self.kind}[{self.severity}]"


class Incident(TenantScopedModel):
    """An operator-tracked incident aggregating related alerts (spec §12.3)."""

    integration = models.ForeignKey(
        Integration, on_delete=models.SET_NULL, null=True, blank=True, related_name="incidents"
    )
    title = models.CharField(max_length=200)
    severity = models.CharField(max_length=12, choices=AlertSeverity.choices)
    status = models.CharField(max_length=16, default="open", db_index=True)
    detail = models.TextField(blank=True, default="")

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"incident:{self.title}[{self.status}]"
