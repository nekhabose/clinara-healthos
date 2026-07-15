"""Generation service interface (spec §7.4).

Loads the approved template catalog once and exposes the constrained drafter. The heavy
logic lives in ``core.py`` (Django-free, tested in isolation). No LLM is called by default
— the deterministic renderer guarantees a safe output path (plan §1.1 invariant 1).
"""
from __future__ import annotations

from functools import lru_cache

from django.conf import settings

from .core import CommunicationTemplate, Draft, draft, load_templates

__all__ = ["get_templates", "draft", "Draft", "CommunicationTemplate"]


@lru_cache(maxsize=1)
def get_templates() -> dict[str, CommunicationTemplate]:
    return load_templates(settings.CLINICAL_TEMPLATES_PATH)
