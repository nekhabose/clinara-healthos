"""Immutable context snapshot (spec §8.3).

Every protocol evaluation uses one of these. It is frozen so a workflow can be replayed
against the exact inputs that produced the original decision (plan §1.1 explainability).
The snapshot records not just facts but their provenance: source ids, timestamps,
freshness, missing facts, conflicts, transformations, mappings, and builder version.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ContextProvenance(BaseModel):
    """Why the snapshot can be trusted and reproduced (spec §8.3 requirements)."""

    model_config = ConfigDict(frozen=True)

    source_record_ids: list[str] = Field(default_factory=list)
    source_timestamps: dict[str, datetime] = Field(default_factory=dict)
    data_freshness_seconds: dict[str, int] = Field(default_factory=dict)
    missing_facts: list[str] = Field(default_factory=list)
    conflicting_facts: list[str] = Field(default_factory=list)
    transformations: list[str] = Field(default_factory=list)
    terminology_mappings: dict[str, str] = Field(default_factory=dict)
    context_builder_version: str


class ContextSnapshot(BaseModel):
    """Immutable facts + provenance for a single protocol evaluation.

    ``facts`` holds the resolved clinical facts (e.g. current_a1c, a1c_trend). Keeping it
    a typed dict lets protocols reference facts by name while the provenance block keeps
    the evaluation auditable and replayable.
    """

    model_config = ConfigDict(frozen=True)

    tenant_id: str
    patient_id: str
    facts: dict[str, Any] = Field(default_factory=dict)
    provenance: ContextProvenance
    context_created_at: datetime

    def has_required(self, required: list[str]) -> bool:
        """True only when every required fact is present (drives automation suppression)."""
        return all(name in self.facts and self.facts[name] is not None for name in required)
