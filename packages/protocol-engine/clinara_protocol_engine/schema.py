"""Declarative rule schema (spec §6.5.3).

Rules are DATA, not code (plan key decision, Phase 1). This module defines the typed shape
a rule YAML must satisfy; ``loader.py`` parses files into these models. Because the schema
is Pydantic, a malformed rule fails loudly at load time rather than misbehaving at
evaluation time.

Conditions support nested boolean logic (``all`` / ``any`` / ``not``) over leaf predicates
of the form ``{fact, operator, value}`` (spec §6.5.5 "nested Boolean logic").
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


class LeafCondition(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    fact: str
    operator: str
    value: Any


class BoolCondition(BaseModel):
    """Exactly one of all/any/not is set (validated)."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    all: list["Condition"] | None = None
    any: list["Condition"] | None = None
    not_: "Condition | None" = Field(default=None, alias="not")

    @model_validator(mode="after")
    def _exactly_one(self) -> "BoolCondition":
        set_count = sum(x is not None for x in (self.all, self.any, self.not_))
        if set_count != 1:
            raise ValueError("a boolean condition must set exactly one of all/any/not")
        return self


Condition = LeafCondition | BoolCondition


class RuleScope(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    specialties: list[str] = Field(default_factory=list)


class RuleThen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    classification: str
    recommended_action: str = "none"
    recommended_interval_days: int | None = None
    priority: str | None = None
    patient_template: str | None = None
    clinician_context: list[str] = Field(default_factory=list)
    reason_codes: list[str] = Field(default_factory=list)


class RuleSafety(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    requires_manual_review: bool = False
    # Fact names that, when truthy in the snapshot, EXCLUDE this rule (protected cohorts).
    excluded_when: list[str] = Field(default_factory=list)


class Rule(BaseModel):
    """One versioned clinical rule (spec §6.5.3)."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    id: str
    version: int
    marker: str  # canonical marker this rule applies to (drives candidate selection)
    scope: RuleScope = Field(default_factory=RuleScope)
    when: Condition
    then: RuleThen
    safety: RuleSafety = Field(default_factory=RuleSafety)


BoolCondition.model_rebuild()
