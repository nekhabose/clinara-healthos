"""Canonical clinical model (spec §8.2) and immutable context snapshot (spec §8.3).

The platform never depends on vendor-specific EHR structures directly. Every inbound
message is transformed into these canonical models, which are the stable inputs to the
protocol engine.
"""

from .canonical import (
    CanonicalClinicalEvent,
    CanonicalEventType,
    CodeableConcept,
    ReferenceRange,
    SourceRef,
    TestResult,
)
from .context import ContextProvenance, ContextSnapshot
from .decision import (
    EvaluationTrace,
    ProtocolEvaluation,
    ResultDecision,
)

__all__ = [
    "CanonicalClinicalEvent",
    "CanonicalEventType",
    "CodeableConcept",
    "ReferenceRange",
    "SourceRef",
    "TestResult",
    "ContextSnapshot",
    "ContextProvenance",
    "ResultDecision",
    "EvaluationTrace",
    "ProtocolEvaluation",
]
