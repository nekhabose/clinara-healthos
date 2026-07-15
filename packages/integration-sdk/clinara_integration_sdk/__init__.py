"""Clinara integration-sdk — adapter-per-source, canonical-in-the-middle (plan Phase 3).

Vendor wire formats (HL7 v2, FHIR) are parsed into the SAME canonical payload the protocol
engine consumes. Integration quirks live here; clinical logic never sees them.
"""

from .hl7v2 import Encoding, Hl7Message, Hl7ParseError, parse, to_canonical_payloads
from .ratelimit import TokenBucket, detect_silent_gap

__all__ = [
    "parse",
    "to_canonical_payloads",
    "Hl7Message",
    "Hl7ParseError",
    "Encoding",
    "TokenBucket",
    "detect_silent_gap",
]
