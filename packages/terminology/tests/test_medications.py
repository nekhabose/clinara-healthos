"""RxNorm medication normalization (plan Phase 4, workstream 2)."""
import pytest
from clinara_terminology import (
    LOW_RISK_REFILL_CLASSES,
    ControlledSchedule,
    MedicationClass,
    UnknownMedicationError,
    map_medication,
)


def test_map_known_rxnorm():
    spec = map_medication("RXNORM", "617314")
    assert spec.name.startswith("Atorvastatin")
    assert spec.med_class is MedicationClass.STATIN
    assert spec.is_controlled is False


def test_controlled_schedule_is_code_defined():
    oxy = map_medication("RXNORM", "1049221")
    assert oxy.schedule is ControlledSchedule.SCHEDULE_II
    assert oxy.is_controlled is True


def test_unknown_code_raises_not_guesses():
    with pytest.raises(UnknownMedicationError):
        map_medication("RXNORM", "000000")
    with pytest.raises(UnknownMedicationError):
        map_medication("NDC", "617314")  # wrong code system


def test_low_risk_allowlist_excludes_controlled_classes():
    assert MedicationClass.STATIN in LOW_RISK_REFILL_CLASSES
    assert MedicationClass.OPIOID not in LOW_RISK_REFILL_CLASSES
    assert MedicationClass.BENZODIAZEPINE not in LOW_RISK_REFILL_CLASSES
