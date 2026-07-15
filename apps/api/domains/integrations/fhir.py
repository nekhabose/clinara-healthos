"""Minimal FHIR R4 Observation parser (plan Phase 1, workstream 1 — sandbox ingestion).

Extracts the fields the canonical pipeline needs from a FHIR ``Observation`` resource into
the simplified payload the workflow orchestrator consumes. Deliberately small: the full
production connection (SMART backend-services auth, the complete resource set) lands in
Phase 3. Vendor parsing lives here, never in protocol logic (adapter pattern).
"""
from __future__ import annotations

from typing import Any


class FhirParseError(ValueError):
    pass


def parse_observation(resource: dict[str, Any]) -> dict[str, Any]:
    """Map a FHIR Observation to the pipeline payload. Raises FhirParseError if unusable."""
    if resource.get("resourceType") != "Observation":
        raise FhirParseError("not a FHIR Observation resource")

    codings = (resource.get("code") or {}).get("coding") or []
    loinc = next((c for c in codings if "loinc" in (c.get("system") or "").lower()), None)
    coding = loinc or (codings[0] if codings else None)
    if not coding or not coding.get("code"):
        raise FhirParseError("Observation has no code")

    system = "LOINC" if (loinc or "loinc" in (coding.get("system") or "").lower()) else (
        coding.get("system") or "unknown"
    )

    qty = resource.get("valueQuantity") or {}
    if "value" not in qty:
        raise FhirParseError("Observation has no valueQuantity")

    subject_ref = (resource.get("subject") or {}).get("reference") or ""
    patient_external_id = subject_ref.split("/")[-1] if subject_ref else resource.get("id", "")

    ref_range = None
    ranges = resource.get("referenceRange") or []
    if ranges:
        r = ranges[0]
        ref_range = {"low": (r.get("low") or {}).get("value"),
                     "high": (r.get("high") or {}).get("value")}

    return {
        "resource_type": "Observation",
        "patient_external_id": patient_external_id,
        "code_system": system,
        "code": coding["code"],
        "value": qty["value"],
        "unit": qty.get("unit") or qty.get("code"),
        "observed_at": resource.get("effectiveDateTime") or resource.get("issued"),
        "reference_range": ref_range,
    }
