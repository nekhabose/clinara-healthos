"""FHIR R4 write-back client (plan Phase 7 — closes gap G3).

Turns an approved Clinara result into the two vendor-facing artifacts Elaborate delivers at
direct release:

  * an **EHR task / inbox item** for the care team → a FHIR ``Task`` resource, and
  * a **patient-portal message** → a FHIR ``Communication`` resource.

This is the *adapter* edge (canonical-in-the-middle, plan §Phase 3): it speaks FHIR to the
EMR and nothing else — no protocol-engine or clinical types cross this boundary. Vendor
differences (base URL, scopes, small resource-shaping quirks) are isolated in
``VendorProfile``; ``EPIC`` and ``ATHENA`` are provided. Auth is delegated to an injected
``SmartBackendAuth`` and the wire call to an injected ``HttpTransport`` — so this is
exercised against a fake FHIR server today and a live sandbox by configuration alone.

HTTP status is classified deterministically: 2xx succeeds, 429/5xx is a *retryable*
``FhirWriteError``, and any other 4xx is *terminal* — the delivery service uses that flag to
decide whether to back off and retry or fail fast to an operator alert.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from .smart import SmartBackendAuth
from .transport import HttpRequest, HttpResponse, HttpTransport, TransportError

_FHIR_JSON = "application/fhir+json"


class FhirWriteError(RuntimeError):
    """A write-back that did not succeed. ``retryable`` marks transient failures (429/5xx/
    network) the caller may retry; terminal failures (4xx) should fail fast."""

    def __init__(self, message: str, *, status: int | None = None, retryable: bool = False):
        super().__init__(message)
        self.status = status
        self.retryable = retryable


@dataclass(frozen=True)
class WriteResult:
    external_id: str
    resource_type: str
    location: str | None = None


@dataclass(frozen=True)
class VendorProfile:
    """Per-EMR quirks kept out of the clinical core. ``task_extra``/``communication_extra``
    let a vendor require extra resource fields without changing the shared builders."""

    name: str
    task_extra: dict[str, Any] = field(default_factory=dict)
    communication_extra: dict[str, Any] = field(default_factory=dict)


EPIC = VendorProfile(name="epic")
# Athena tags portal Communications with a category so they surface in the patient inbox.
ATHENA = VendorProfile(
    name="athena",
    communication_extra={
        "category": [{"coding": [{"code": "notification", "display": "Patient notification"}]}]
    },
)


class FhirWriteBackClient:
    """Idempotency, retry, and confirmation live in the delivery service; this client makes a
    single confirmed FHIR write and reports success or a classified failure."""

    def __init__(
        self,
        *,
        base_url: str,
        auth: SmartBackendAuth,
        transport: HttpTransport,
        clock: Callable[[], float],
        profile: VendorProfile = EPIC,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._auth = auth
        self._transport = transport
        self._clock = clock
        self._profile = profile

    # ---- public API ----

    def create_task(
        self, *, patient_ref: str, note: str, requester: str = "Clinara",
        priority: str = "routine",
    ) -> WriteResult:
        """Write an EHR inbox Task for the care team (FHIR R4 ``Task``)."""
        resource = {
            "resourceType": "Task",
            "status": "requested",
            "intent": "order",
            "priority": priority,
            "description": note,
            "for": {"reference": _patient_reference(patient_ref)},
            "requester": {"display": requester},
            "authoredOn": _iso(self._clock()),
            **self._profile.task_extra,
        }
        return self._post("Task", resource)

    def create_communication(
        self, *, patient_ref: str, body: str, subject: str = "",
    ) -> WriteResult:
        """Write a patient-portal message (FHIR R4 ``Communication``)."""
        resource: dict[str, Any] = {
            "resourceType": "Communication",
            "status": "completed",
            "subject": {"reference": _patient_reference(patient_ref)},
            "recipient": [{"reference": _patient_reference(patient_ref)}],
            "sent": _iso(self._clock()),
            "payload": [{"contentString": (f"{subject}\n\n{body}" if subject else body)}],
            **self._profile.communication_extra,
        }
        return self._post("Communication", resource)

    # ---- internals ----

    def _post(self, resource_type: str, resource: dict[str, Any]) -> WriteResult:
        import json as _json

        now = self._clock()
        headers = {
            "Content-Type": _FHIR_JSON,
            "Accept": _FHIR_JSON,
            **self._auth.bearer_header(now),
        }
        try:
            resp = self._transport.request(
                HttpRequest(
                    method="POST",
                    url=f"{self._base_url}/{resource_type}",
                    headers=headers,
                    body=_json.dumps(resource).encode("utf-8"),
                )
            )
        except TransportError as exc:  # network failure is transient → retryable
            raise FhirWriteError(f"transport error: {exc}", retryable=True) from exc

        if resp.ok:
            return WriteResult(
                external_id=_extract_id(resp, resource_type),
                resource_type=resource_type,
                location=resp.header("Location"),
            )
        raise _classify(resp, resource_type)


def _classify(resp: HttpResponse, resource_type: str) -> FhirWriteError:
    detail = resp.body.decode("utf-8", "replace")[:300] if resp.body else ""
    retryable = resp.status == 429 or resp.status >= 500
    return FhirWriteError(
        f"{resource_type} write failed: {resp.status} {detail}",
        status=resp.status,
        retryable=retryable,
    )


def _extract_id(resp: HttpResponse, resource_type: str) -> str:
    """Prefer the id in the returned resource body; fall back to the Location header
    (``.../Task/123/_history/1`` → ``123``)."""
    try:
        data = resp.json() or {}
    except ValueError:
        data = {}
    if isinstance(data, dict) and data.get("id"):
        return str(data["id"])
    location = resp.header("Location")
    if location:
        parts = [p for p in location.split("/") if p]
        if resource_type in parts:
            idx = parts.index(resource_type)
            if idx + 1 < len(parts):
                return parts[idx + 1]
        return parts[-1]
    raise FhirWriteError(f"{resource_type} write returned no id", status=resp.status)


def _patient_reference(patient_ref: str) -> str:
    return patient_ref if "/" in patient_ref else f"Patient/{patient_ref}"


def _iso(now_epoch: float) -> str:
    from datetime import datetime, timezone

    return datetime.fromtimestamp(now_epoch, tz=timezone.utc).isoformat()


__all__ = [
    "FhirWriteBackClient",
    "FhirWriteError",
    "WriteResult",
    "VendorProfile",
    "EPIC",
    "ATHENA",
]
