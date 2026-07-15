"""Canonical clinical event (spec §8.2).

This is the vendor-neutral shape every inbound EHR/lab message is normalized into.
It supports stable protocol inputs, cross-EHR workflows, consistent terminology,
historical trend calculation, reprocessing, and auditability.
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class CanonicalEventType(str, Enum):
    LAB_RESULT = "lab_result"
    DIAGNOSTIC_REPORT = "diagnostic_report"
    PATIENT_MESSAGE = "patient_message"
    REFILL_REQUEST = "refill_request"
    ENCOUNTER = "encounter"
    PATIENT = "patient"


class SourceRef(BaseModel):
    model_config = ConfigDict(frozen=True)
    system: str
    message_id: str


class CodeableConcept(BaseModel):
    model_config = ConfigDict(frozen=True)
    code_system: str  # e.g. "LOINC", "RxNorm"
    code: str
    canonical_name: str | None = None


class ReferenceRange(BaseModel):
    model_config = ConfigDict(frozen=True)
    low: float | None = None
    high: float | None = None


class TestResult(BaseModel):
    model_config = ConfigDict(frozen=True)
    code_system: str
    code: str
    canonical_name: str | None = None
    value: float | str
    unit: str | None = None
    reference_range: ReferenceRange | None = None


class CanonicalClinicalEvent(BaseModel):
    """The canonical event (spec §8.2 example is a lab result)."""

    model_config = ConfigDict(frozen=True)

    tenant_id: str
    patient_id: str  # internal, resolved by the patient-matching service
    event_type: CanonicalEventType
    source: SourceRef
    test: TestResult | None = None
    observed_at: datetime
    ingested_at: datetime | None = None
    raw_message_ref: str | None = Field(
        default=None, description="Pointer to the stored raw payload (never dropped)."
    )
