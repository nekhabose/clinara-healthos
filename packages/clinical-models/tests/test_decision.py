"""ResultDecision safety properties (spec §6.1.5/§6.1.6)."""
from clinara_clinical_models import ResultDecision
from clinara_shared_types import AutomationStatus, Priority, ResultClassification


def _decision(classification, automation=AutomationStatus.REQUIRES_CLINICIAN_APPROVAL):
    return ResultDecision(
        classification=classification, priority=Priority.NORMAL,
        recommended_action="none", automation_status=automation,
    )


def test_is_critical():
    assert _decision(ResultClassification.CRITICAL_ESCALATION).is_critical is True
    assert _decision(ResultClassification.NORMAL).is_critical is False


def test_requires_human_for_all_unsafe_classifications():
    for c in (
        ResultClassification.CRITICAL_ESCALATION,
        ResultClassification.HIGH_PRIORITY_REVIEW,
        ResultClassification.CONFLICTING_DATA,
        ResultClassification.INSUFFICIENT_DATA,
        ResultClassification.UNSUPPORTED,
    ):
        assert _decision(c).requires_human is True


def test_decision_is_frozen():
    import pydantic
    d = _decision(ResultClassification.NORMAL)
    try:
        d.classification = ResultClassification.CRITICAL_ESCALATION
        raise AssertionError("decision must be immutable")
    except pydantic.ValidationError:
        pass
