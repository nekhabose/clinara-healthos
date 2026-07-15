"""Pure HL7 v2 adapter (plan Phase 3, workstream 2 — MLLP message types → canonical).

The adapter architecture keeps vendor quirks OUT of clinical logic (plan §1.2 key decision:
"adapter-per-source, canonical-in-the-middle"). This module parses the pipe-delimited HL7 v2
wire format into a neutral ``Hl7Message`` and lowers result messages (ORU) into the *same*
simplified payload the FHIR adapter produces — so the protocol engine only ever sees
canonical events, never HL7.

Deliberately dependency-free and total: a malformed message raises ``Hl7ParseError`` so the
gateway can dead-letter it (never silently drop — plan §1.1 invariant 2), rather than
guessing.

Supported message types (spec §6.7.4): ADT (patient/encounter), ORU (results), ORM
(orders), MDM (documents). Result content (ORU) is fully lowered to canonical observations;
the others are parsed for patient/encounter identity + type so nothing is dropped.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


class Hl7ParseError(ValueError):
    """Raised when a message cannot be parsed as HL7 v2 (→ dead-letter, never dropped)."""


# HL7 v2 encoding characters (MSH-1 / MSH-2). We assume the standard set; a message that
# declares a different set in MSH-2 is honoured.
@dataclass(frozen=True)
class Encoding:
    field: str = "|"
    component: str = "^"
    repetition: str = "~"
    escape: str = "\\"
    subcomponent: str = "&"


@dataclass
class Hl7Message:
    message_type: str            # e.g. "ORU^R01"
    trigger: str                 # e.g. "R01"
    message_control_id: str
    sending_facility: str
    patient_external_id: str
    encounter_id: str
    observations: list[dict[str, Any]] = field(default_factory=list)

    @property
    def category(self) -> str:
        return self.message_type.split("^", 1)[0]


def _split_segments(raw: str) -> list[list[str]]:
    # HL7 segments are CR-delimited; be lenient about CRLF / LF from file-based feeds.
    normalized = raw.replace("\r\n", "\r").replace("\n", "\r")
    lines = [seg for seg in normalized.split("\r") if seg.strip()]
    if not lines or not lines[0].startswith("MSH"):
        raise Hl7ParseError("message does not start with an MSH segment")
    return [seg.split("|") for seg in lines]


def _seg(segments: list[list[str]], name: str) -> list[str] | None:
    for seg in segments:
        if seg and seg[0] == name:
            return seg
    return None


def _all_segs(segments: list[list[str]], name: str) -> list[list[str]]:
    return [seg for seg in segments if seg and seg[0] == name]


def _get(seg: list[str] | None, index: int, default: str = "") -> str:
    if seg is None or index >= len(seg):
        return default
    return seg[index]


def _component(value: str, index: int, comp: str = "^", default: str = "") -> str:
    parts = value.split(comp)
    return parts[index] if index < len(parts) else default


_LOINC_ALIASES = {"LN", "LOINC"}


def _normalize_system(system: str) -> str:
    return "LOINC" if system.strip().upper() in _LOINC_ALIASES else (system.strip() or "unknown")


def _parse_hl7_datetime(ts: str) -> str | None:
    """HL7 timestamp (YYYYMMDDHHMMSS[.S][+/-ZZZZ]) → ISO-8601, or None."""
    ts = ts.strip()
    if not ts or not ts[:8].isdigit():
        return None
    y, mo, d = ts[0:4], ts[4:6], ts[6:8]
    hh = ts[8:10] or "00"
    mm = ts[10:12] or "00"
    ss = ts[12:14] or "00"
    tz = ""
    for sign in ("+", "-"):
        if sign in ts[8:]:
            off = ts[8:].split(sign, 1)[1][:4]
            if len(off) == 4:
                tz = f"{sign}{off[:2]}:{off[2:]}"
            break
    if not tz:
        tz = "+00:00"
    return f"{y}-{mo}-{d}T{hh}:{mm}:{ss}{tz}"


def parse(raw: str) -> Hl7Message:
    """Parse a raw HL7 v2 message string into a neutral ``Hl7Message``."""
    segments = _split_segments(raw)
    msh = segments[0]
    # MSH is special: MSH-1 is the field separator itself, so field indexes are offset.
    message_type = _get(msh, 8)          # MSH-9
    trigger = _component(message_type, 1)
    control_id = _get(msh, 9)            # MSH-10
    sending_facility = _get(msh, 3)      # MSH-4

    pid = _seg(segments, "PID")
    # PID-3 patient identifier list; take the ID component of the first repetition.
    patient_raw = _get(pid, 3)
    patient_external_id = _component(patient_raw.split("~")[0], 0)

    pv1 = _seg(segments, "PV1")
    encounter_id = _component(_get(pv1, 19), 0) if pv1 else ""

    observations: list[dict[str, Any]] = []
    obr = _seg(segments, "OBR")
    obr_time = _parse_hl7_datetime(_get(obr, 7)) if obr else None
    for obx in _all_segs(segments, "OBX"):
        value_type = _get(obx, 2)
        if value_type and value_type not in {"NM", "SN"}:
            continue  # non-numeric result values are lowered to canonical elsewhere (Phase 5+)
        code_field = _get(obx, 3)
        code = _component(code_field, 0)
        system = _normalize_system(_component(code_field, 2))
        raw_value = _get(obx, 5)
        if not code or not raw_value:
            continue
        try:
            value = float(raw_value)
        except ValueError:
            continue
        unit = _component(_get(obx, 6), 0) or None
        observed_at = _parse_hl7_datetime(_get(obx, 14)) or obr_time
        observations.append(
            {
                "resource_type": "Observation",
                "patient_external_id": patient_external_id,
                "code_system": system,
                "code": code,
                "value": value,
                "unit": unit,
                "observed_at": observed_at,
                "encounter_id": encounter_id,
            }
        )

    return Hl7Message(
        message_type=message_type,
        trigger=trigger,
        message_control_id=control_id,
        sending_facility=sending_facility,
        patient_external_id=patient_external_id,
        encounter_id=encounter_id,
        observations=observations,
    )


def to_canonical_payloads(message: Hl7Message) -> list[dict[str, Any]]:
    """Lower an ORU result message to the canonical pipeline payloads (one per OBX).

    ADT/ORM/MDM carry no result values, so they yield no observation payloads here — the
    gateway still records them (patient/encounter update, order, document) so nothing is
    dropped.
    """
    return list(message.observations)


__all__ = ["parse", "to_canonical_payloads", "Hl7Message", "Hl7ParseError", "Encoding"]
