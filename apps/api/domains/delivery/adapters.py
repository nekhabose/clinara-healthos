"""Real EMR write-back adapters (plan Phase 7 — closes G3).

Bridges the delivery domain's ``EhrClient`` seam to the FHIR write-back client in
``clinara_integration_sdk``. The delivery *service* keeps all governance (idempotency,
confirmation, retry, audit, events); this adapter only translates a channel + payload into
the right FHIR resource and reports the external id (or raises).

Channel mapping (the two artifacts Elaborate delivers at direct release):
  * ``ehr_task``       → FHIR ``Task``          (care-team inbasket item)
  * ``patient_portal`` → FHIR ``Communication`` (patient-portal message)

The SDK client's HTTP transport and JWT signer are injected, so this is exercised against a
vendor-emulating fake in tests and pointed at a live Epic/Athena endpoint purely by the
``EHR_WRITE_BACK`` settings block — no code change. A failure raised here carries the SDK's
``retryable`` flag so the delivery service can back off on transient errors (429/5xx/network)
and fail fast on terminal ones (4xx).
"""
from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

from clinara_integration_sdk import (
    EPIC,
    FhirWriteBackClient,
    HmacSigner,
    SmartBackendAuth,
    SmartConfig,
    UrllibTransport,
    VendorProfile,
)
from clinara_integration_sdk.fhir_writeback import ATHENA

from .models import OutboundChannel

_PROFILES: dict[str, VendorProfile] = {"epic": EPIC, "athena": ATHENA}


class SmartEhrClient:
    """An ``EhrClient`` backed by a real FHIR write-back client."""

    def __init__(self, fhir_client: FhirWriteBackClient, *, requester: str = "Clinara") -> None:
        self._fhir = fhir_client
        self._requester = requester

    def send(self, *, channel: str, target: str, subject: str, body: str) -> str:
        if channel == OutboundChannel.EHR_TASK:
            note = f"{subject}: {body}" if subject else (body or "Result ready for review")
            return self._fhir.create_task(
                patient_ref=target, note=note, requester=self._requester
            ).external_id
        if channel == OutboundChannel.PATIENT_PORTAL:
            return self._fhir.create_communication(
                patient_ref=target, body=body, subject=subject
            ).external_id
        raise ValueError(f"SmartEhrClient cannot deliver channel {channel!r}")


def build_smart_ehr_client(
    *,
    config: dict[str, Any],
    signer: Any,
    transport: Any | None = None,
    clock: Callable[[], float] | None = None,
    jti_factory: Callable[[], str] | None = None,
) -> SmartEhrClient:
    """Construct a ``SmartEhrClient`` from a vendor config block.

    ``config`` keys: ``base_url``, ``token_url``, ``client_id``, ``scopes`` (list), and
    optional ``vendor`` (``epic``/``athena``). The JWT ``signer`` is injected by the caller
    (production: an RS384 signer over a vault-held key; dev/test: ``HmacSigner``) so no key
    material lives in this process by default.
    """
    import uuid

    clock = clock or time.time
    transport = transport or UrllibTransport()
    jti_factory = jti_factory or (lambda: str(uuid.uuid4()))
    smart = SmartConfig(
        client_id=config["client_id"],
        token_url=config["token_url"],
        scopes=tuple(config.get("scopes", ())),
    )
    auth = SmartBackendAuth(smart, signer, transport, jti_factory=jti_factory)
    fhir = FhirWriteBackClient(
        base_url=config["base_url"], auth=auth, transport=transport, clock=clock,
        profile=_PROFILES.get(config.get("vendor", "epic"), EPIC),
    )
    return SmartEhrClient(fhir, requester=config.get("requester", "Clinara"))


def client_from_settings(vendor: str, *, signer: Any, **kwargs: Any) -> SmartEhrClient:
    """Build a client from ``settings.EHR_WRITE_BACK[vendor]``.

    Kept out of import-time so a deployment without write-back configured never fails to boot.
    A dev signer is used only if the settings block does not inject one; production supplies
    an RS384 signer.
    """
    from django.conf import settings

    profiles = getattr(settings, "EHR_WRITE_BACK", {}) or {}
    if vendor not in profiles:
        raise KeyError(f"no EHR_WRITE_BACK config for vendor {vendor!r}")
    cfg = dict(profiles[vendor])
    cfg.setdefault("vendor", vendor)
    return build_smart_ehr_client(config=cfg, signer=signer, **kwargs)


def dev_signer(secret: str = "clinara-dev-signing-key") -> HmacSigner:
    """A local/dev HMAC signer. NEVER for production — real EMRs require asymmetric keys."""
    return HmacSigner(secret.encode())


__all__ = [
    "SmartEhrClient",
    "build_smart_ehr_client",
    "client_from_settings",
    "dev_signer",
]
