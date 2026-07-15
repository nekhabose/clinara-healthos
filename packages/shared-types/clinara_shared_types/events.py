"""Immutable, versioned domain event envelope (spec §7.5).

Every event on the bus is wrapped in this envelope. It is frozen (immutable),
schema-versioned, tenant-aware, and carries correlation + causation + idempotency ids
plus retry/dead-letter policy metadata.
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class EventType(str, Enum):
    """Core domain events (spec §7.5)."""

    PATIENT_UPDATED = "PatientUpdated"
    ENCOUNTER_UPDATED = "EncounterUpdated"
    OBSERVATION_RECEIVED = "ObservationReceived"
    DIAGNOSTIC_REPORT_RECEIVED = "DiagnosticReportReceived"
    PATIENT_MESSAGE_RECEIVED = "PatientMessageReceived"
    REFILL_REQUEST_RECEIVED = "RefillRequestReceived"
    # Phase 4 — Prescription & Refill Intelligence:
    REFILL_EVALUATED = "RefillEvaluated"
    REFILL_DECIDED = "RefillDecided"
    CONTEXT_BUILT = "ContextBuilt"
    PROTOCOL_EVALUATED = "ProtocolEvaluated"
    DECISION_CREATED = "DecisionCreated"
    COMMUNICATION_GENERATED = "CommunicationGenerated"
    COMMUNICATION_VALIDATED = "CommunicationValidated"
    WORKFLOW_ESCALATED = "WorkflowEscalated"
    DELIVERY_SUCCEEDED = "DeliverySucceeded"
    DELIVERY_FAILED = "DeliveryFailed"
    CLINICIAN_APPROVED = "ClinicianApproved"
    CLINICIAN_EDITED = "ClinicianEdited"
    CLINICIAN_OVERRODE = "ClinicianOverrode"
    PATIENT_RESPONDED = "PatientResponded"
    # Phase 2 — Clinical Rule Studio lifecycle (spec §6.5.4/§6.5.8):
    PROTOCOL_SIMULATED = "ProtocolSimulated"
    PROTOCOL_APPROVED = "ProtocolApproved"
    PROTOCOL_DEPLOYED = "ProtocolDeployed"
    PROTOCOL_ROLLED_BACK = "ProtocolRolledBack"
    MAPPING_CHANGED = "MappingChanged"


class RetryPolicy(BaseModel):
    model_config = ConfigDict(frozen=True)
    max_attempts: int = 8
    backoff_seconds: int = 30
    dead_letter: bool = True


class DomainEvent(BaseModel):
    """The event envelope. Immutable by contract (spec §7.5)."""

    model_config = ConfigDict(frozen=True)

    event_type: EventType
    schema_version: int = 1
    tenant_id: str | None = None
    correlation_id: str
    causation_id: str | None = None
    idempotency_id: str
    occurred_at: datetime
    source: str
    payload: dict[str, Any] = Field(default_factory=dict)
    audit_metadata: dict[str, Any] = Field(default_factory=dict)
    retry_policy: RetryPolicy = Field(default_factory=RetryPolicy)
