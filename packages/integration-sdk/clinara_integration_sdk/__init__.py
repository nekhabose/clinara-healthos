"""Clinara integration-sdk — adapter-per-source, canonical-in-the-middle (plan Phase 3+7).

Vendor wire formats (HL7 v2, FHIR) are parsed into the SAME canonical payload the protocol
engine consumes, and outbound write-back speaks FHIR to the EMR — integration quirks live
here; clinical logic never sees them.

Phase 7 (Real EMR Connectivity) adds the outbound edge: SMART Backend Services auth
(``smart``), the FHIR R4 write-back client (``fhir_writeback``), a pure retry policy
(``retry``), and the injectable HTTP transport (``transport``) they run on.
"""

from .fhir_writeback import (
    ATHENA,
    EPIC,
    FhirWriteBackClient,
    FhirWriteError,
    VendorProfile,
    WriteResult,
)
from .hl7v2 import Encoding, Hl7Message, Hl7ParseError, parse, to_canonical_payloads
from .ratelimit import TokenBucket, detect_silent_gap
from .retry import NO_RETRY, RetryPolicy
from .smart import (
    AccessToken,
    HmacSigner,
    Signer,
    SmartAuthError,
    SmartBackendAuth,
    SmartConfig,
    build_client_assertion,
)
from .smart_launch import (
    HmacVerifier,
    LaunchConfig,
    LaunchContext,
    SmartEndpoints,
    SmartLaunchError,
    Verifier,
    build_authorize_url,
    build_test_id_token,
    decode_id_token,
    discover_endpoints,
    exchange_code,
)
from .transport import (
    HttpRequest,
    HttpResponse,
    HttpTransport,
    TransportError,
    UrllibTransport,
)

__all__ = [
    # HL7 v2 / rate limiting (Phase 3)
    "parse",
    "to_canonical_payloads",
    "Hl7Message",
    "Hl7ParseError",
    "Encoding",
    "TokenBucket",
    "detect_silent_gap",
    # Transport (Phase 7)
    "HttpRequest",
    "HttpResponse",
    "HttpTransport",
    "UrllibTransport",
    "TransportError",
    # SMART Backend Services auth (Phase 7)
    "SmartBackendAuth",
    "SmartConfig",
    "AccessToken",
    "Signer",
    "HmacSigner",
    "SmartAuthError",
    "build_client_assertion",
    # SMART App Launch — EHR launch flow (Phase 8)
    "LaunchConfig",
    "SmartEndpoints",
    "LaunchContext",
    "Verifier",
    "HmacVerifier",
    "SmartLaunchError",
    "discover_endpoints",
    "build_authorize_url",
    "exchange_code",
    "decode_id_token",
    "build_test_id_token",
    # FHIR write-back (Phase 7)
    "FhirWriteBackClient",
    "FhirWriteError",
    "WriteResult",
    "VendorProfile",
    "EPIC",
    "ATHENA",
    # Retry (Phase 7)
    "RetryPolicy",
    "NO_RETRY",
]
