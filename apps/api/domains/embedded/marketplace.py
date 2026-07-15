"""Marketplace app manifests for EHR distribution (plan Phase 8 — G4 workstream 4).

Elaborate is distributed *inside* the EHR — listed in the Epic Showroom and the Athena
Marketplace. That listing is a declarative SMART-app manifest: the launch URL, redirect URIs,
requested scopes, and supported FHIR version the EHR needs to register and launch the app.

This module is the deterministic validator for those manifests (the manifests themselves live
as JSON under ``clinical/marketplace/``). Keeping validation in code means a malformed listing
— a missing redirect URI, an EHR launch that forgot the ``launch`` scope, an unsupported FHIR
version — is caught by a test, not by a failed marketplace submission. Django-free and pure.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

# Every SMART EHR-launch app listing must declare at least these.
REQUIRED_FIELDS = (
    "app_name",
    "vendor",
    "launch_url",
    "redirect_uris",
    "scopes",
    "fhir_version",
    "launch_type",
)
_SUPPORTED_VENDORS = {"epic", "athena"}
_SUPPORTED_FHIR = {"4.0.1"}
# An EHR-launch app must request these to be signed in by the EHR with a chart context.
_REQUIRED_SCOPES = {"openid", "fhirUser", "launch"}


def validate_manifest(manifest: dict[str, Any]) -> list[str]:
    """Return a list of human-readable problems with a manifest (empty ⇒ valid).

    Deterministic and total — it never raises on bad input, it reports. Checks presence of the
    required fields, a known vendor + FHIR version, an ``ehr`` launch type, https redirect URIs,
    and that the identity/launch scopes are present.
    """
    errors: list[str] = []
    for field in REQUIRED_FIELDS:
        if not manifest.get(field):
            errors.append(f"missing required field: {field}")
    if errors:
        return errors  # further checks assume the fields exist

    if manifest["vendor"] not in _SUPPORTED_VENDORS:
        errors.append(f"unsupported vendor: {manifest['vendor']}")
    if manifest["fhir_version"] not in _SUPPORTED_FHIR:
        errors.append(f"unsupported fhir_version: {manifest['fhir_version']}")
    if manifest["launch_type"] != "ehr":
        errors.append("launch_type must be 'ehr' for an embedded EHR launch")

    if not manifest["launch_url"].startswith("https://"):
        errors.append("launch_url must be https")
    redirects = manifest["redirect_uris"]
    if not isinstance(redirects, list) or not redirects:
        errors.append("redirect_uris must be a non-empty list")
    else:
        for uri in redirects:
            if not str(uri).startswith("https://"):
                errors.append(f"redirect_uri must be https: {uri}")

    scopes = set(manifest["scopes"]) if isinstance(manifest["scopes"], list) else set()
    missing_scopes = _REQUIRED_SCOPES - scopes
    if missing_scopes:
        errors.append(f"missing required scopes: {sorted(missing_scopes)}")
    return errors


def load_manifest(path: str | Path) -> dict[str, Any]:
    """Read and parse a manifest JSON file."""
    return json.loads(Path(path).read_text())


def load_manifests(directory: str | Path) -> dict[str, dict[str, Any]]:
    """Load every ``*.json`` manifest in a directory, keyed by filename stem."""
    directory = Path(directory)
    return {p.stem: load_manifest(p) for p in sorted(directory.glob("*.json"))}


__all__ = ["validate_manifest", "load_manifest", "load_manifests", "REQUIRED_FIELDS"]
