"""EHR-embedded clinician surface (plan Phase 8 — closes gaps G4 + G5).

Lets a clinician open Clinara *inside* their EHR via a SMART-on-FHIR EHR launch — no separate
login — with the review surface and a live chart-context panel scoped to the launched chart.
The pure launch/validation flow lives in ``clinara_integration_sdk.smart_launch``; this domain
owns the persistence (issuer→tenant routing, EHR-identity links, launch sessions) and the
identity bridge that preserves tenant isolation and audit.
"""
