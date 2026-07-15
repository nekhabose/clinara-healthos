"""Pure helpers for the EHR-embedded surface (Django-free, deterministic).

The launch protocol itself lives in ``clinara_integration_sdk.smart_launch``; the persistence
and orchestration live in ``services``. This module holds only the small pure predicates that
both use — session liveness and the LaunchConfig projection — so they are unit-testable
without a database or network.
"""
from __future__ import annotations

from datetime import datetime

from clinara_integration_sdk import LaunchConfig

# A launch session that never completes is only useful for a short window; after this it is
# treated as stale so a leaked ``state`` cannot be redeemed long after the fact.
PENDING_LAUNCH_TTL_SECONDS = 600  # 10 minutes to complete the authorize→callback round-trip


def launch_config(*, client_id: str, redirect_uri: str, scopes: list[str] | None) -> LaunchConfig:
    """Project a stored ``EhrConnection`` into the SDK's immutable ``LaunchConfig``.

    Always guarantees the identity scopes (``openid`` + ``fhirUser``) and ``launch`` are
    present, in a stable order, so the app reliably receives an id_token + launch context even
    if a connection was registered with a narrower list.
    """
    requested = list(scopes or [])
    for required in ("openid", "fhirUser", "launch"):
        if required not in requested:
            requested.append(required)
    return LaunchConfig(client_id=client_id, redirect_uri=redirect_uri,
                        scopes=tuple(requested))


def session_is_live(*, status: str, expires_at: datetime | None, now: datetime) -> bool:
    """A bridged session is live only while ACTIVE and before its hard expiry.

    Expiry is stamped from the EHR token's ``expires_in`` at bridge time, so the Clinara
    session cannot outlive the EHR session (plan Phase 8 exit gate — "expires with the EHR
    session"). Fail-closed: any non-active status or a missing/past expiry is not live.
    """
    if status != "active":
        return False
    if expires_at is None:
        return False
    return now < expires_at
