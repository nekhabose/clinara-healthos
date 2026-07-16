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
    # Phase 5 — Patient Message Intelligence:
    MESSAGE_CLASSIFIED = "MessageClassified"
    MESSAGE_ROUTED = "MessageRouted"
    # Phase 6 — Analytics & Personalization:
    FEEDBACK_CAPTURED = "FeedbackCaptured"
    RECOMMENDATION_CREATED = "RecommendationCreated"
    RECOMMENDATION_APPROVED = "RecommendationApproved"
    CONTEXT_BUILT = "ContextBuilt"
    PROTOCOL_EVALUATED = "ProtocolEvaluated"
    DECISION_CREATED = "DecisionCreated"
    COMMUNICATION_GENERATED = "CommunicationGenerated"
    COMMUNICATION_VALIDATED = "CommunicationValidated"
    WORKFLOW_ESCALATED = "WorkflowEscalated"
    DELIVERY_SUCCEEDED = "DeliverySucceeded"
    DELIVERY_FAILED = "DeliveryFailed"
    # Phase 7 — Real EMR Connectivity (write-back release + degraded-channel alert):
    RESULT_RELEASED = "ResultReleased"
    WRITE_BACK_DEGRADED = "WriteBackDegraded"
    # Phase 8 — EHR-Embedded Clinician Surface (SMART-on-FHIR launch, identity bridge):
    EHR_LAUNCHED = "EhrLaunched"
    EHR_LAUNCH_DENIED = "EhrLaunchDenied"
    CLINICIAN_APPROVED = "ClinicianApproved"
    CLINICIAN_EDITED = "ClinicianEdited"
    CLINICIAN_OVERRODE = "ClinicianOverrode"
    PATIENT_RESPONDED = "PatientResponded"
    # Phase 9 — Billing & Coding Intelligence (deterministic, human-confirmed suggestions):
    CODING_SUGGESTIONS_GENERATED = "CodingSuggestionsGenerated"
    CODING_SUGGESTION_CONFIRMED = "CodingSuggestionConfirmed"
    CODING_SUGGESTION_REJECTED = "CodingSuggestionRejected"
    CODING_SUGGESTION_EXPORTED = "CodingSuggestionExported"
    # Phase 10 — Specialty Protocol Breadth (per-tenant threshold customization):
    SPECIALTY_THRESHOLD_UPDATED = "SpecialtyThresholdUpdated"
    SPECIALTY_THRESHOLD_RESET = "SpecialtyThresholdReset"
    # Phase 11 — Data Lifecycle & Compliance Hardening (retention/purge, BAA termination):
    RETENTION_POLICY_UPDATED = "RetentionPolicyUpdated"
    DATA_PURGED = "DataPurged"                 # a scheduled minimization/purge run completed
    TENANT_DATA_PURGED = "TenantDataPurged"    # a BAA-termination hard-purge completed
    # Phase 2 — Clinical Rule Studio lifecycle (spec §6.5.4/§6.5.8):
    PROTOCOL_SIMULATED = "ProtocolSimulated"
    PROTOCOL_APPROVED = "ProtocolApproved"
    PROTOCOL_DEPLOYED = "ProtocolDeployed"
    PROTOCOL_ROLLED_BACK = "ProtocolRolledBack"
    MAPPING_CHANGED = "MappingChanged"
    # GA hardening — emergency controls, reliability, DR, compliance (spec §11.4/§10.2/§15/§10.1):
    KILL_SWITCH_ENGAGED = "KillSwitchEngaged"
    KILL_SWITCH_RELEASED = "KillSwitchReleased"
    BREAK_GLASS_GRANTED = "BreakGlassGranted"
    BREAK_GLASS_REVOKED = "BreakGlassRevoked"
    SLO_BREACHED = "SLOBreached"
    DR_RECONCILED = "DisasterRecoveryReconciled"
    ATTESTATION_GENERATED = "AttestationGenerated"


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
