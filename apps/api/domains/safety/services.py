"""Safety service interface (spec §7.4).

Re-exports the validation gate. The logic lives in ``core.py`` (Django-free, tested in
isolation). The gate is mandatory: no generated message reaches a review queue without
passing it, and any failure falls back to an approved fixed template (spec §6.9.6).
"""
from __future__ import annotations

from .core import FALLBACK_PATIENT_MESSAGE, ValidationResult, validate

__all__ = ["validate", "ValidationResult", "FALLBACK_PATIENT_MESSAGE"]
