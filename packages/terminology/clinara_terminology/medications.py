"""RxNorm medication catalog + normalization (plan Phase 4, workstream 2).

Refills are higher-risk than results (controlled substances, contraindications), so
medication identity is resolved deterministically and **missing identity blocks automation**
(spec §6.3.5). This module maps a vendor medication code (RxNorm in the seed set) to a
canonical medication with its therapeutic class and controlled-substance schedule — the
facts the deterministic refill engine reasons over. Unknown codes raise so the caller can
block/queue, never guess.

Controlled-substance schedule is a first-class, code-defined property: a client/clinician
configuration can never *loosen* it (spec §6.3.5, plan Phase 4 key decision).
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class MedicationClass(str, Enum):
    STATIN = "statin"
    ACE_INHIBITOR = "ace_inhibitor"
    BIGUANIDE = "biguanide"                 # e.g. metformin
    SSRI = "ssri"
    BENZODIAZEPINE = "benzodiazepine"       # controlled
    OPIOID = "opioid"                       # controlled
    STIMULANT = "stimulant"                 # controlled
    PROTON_PUMP_INHIBITOR = "ppi"


class ControlledSchedule(str, Enum):
    NONE = "none"
    SCHEDULE_II = "cii"
    SCHEDULE_III = "ciii"
    SCHEDULE_IV = "civ"


@dataclass(frozen=True)
class MedicationSpec:
    rxnorm: str
    name: str
    med_class: MedicationClass
    schedule: ControlledSchedule

    @property
    def is_controlled(self) -> bool:
        return self.schedule is not ControlledSchedule.NONE


# Seed RxNorm → canonical medication map. Real deployments extend this per tenant; unknown
# codes are blocked/queued, never guessed (spec §6.3.5).
MEDICATION_SPECS: dict[str, MedicationSpec] = {
    "617314": MedicationSpec("617314", "Atorvastatin 10 MG", MedicationClass.STATIN,
                             ControlledSchedule.NONE),
    "197361": MedicationSpec("197361", "Lisinopril 10 MG", MedicationClass.ACE_INHIBITOR,
                             ControlledSchedule.NONE),
    "860975": MedicationSpec("860975", "Metformin 500 MG", MedicationClass.BIGUANIDE,
                             ControlledSchedule.NONE),
    "312961": MedicationSpec("312961", "Simvastatin 20 MG", MedicationClass.STATIN,
                             ControlledSchedule.NONE),
    "310798": MedicationSpec("310798", "Sertraline 50 MG", MedicationClass.SSRI,
                             ControlledSchedule.NONE),
    "197590": MedicationSpec("197590", "Diazepam 5 MG", MedicationClass.BENZODIAZEPINE,
                             ControlledSchedule.SCHEDULE_IV),
    "1049221": MedicationSpec("1049221", "Oxycodone 5 MG", MedicationClass.OPIOID,
                              ControlledSchedule.SCHEDULE_II),
    "541878": MedicationSpec("541878", "Methylphenidate 10 MG", MedicationClass.STIMULANT,
                             ControlledSchedule.SCHEDULE_II),
}


class UnknownMedicationError(KeyError):
    """Raised when an RxNorm code has no canonical mapping (→ block automation)."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(f"unmapped medication code {code}")


def map_medication(code_system: str, code: str) -> MedicationSpec:
    """Resolve a vendor medication code to a canonical spec. Raises if unmapped."""
    if code_system.strip().upper() == "RXNORM":
        spec = MEDICATION_SPECS.get(code.strip())
        if spec is not None:
            return spec
    raise UnknownMedicationError(code)


# Therapeutic classes explicitly approved for streamlined (low-risk) refill handling. This
# is a conservative allowlist; anything not here routes to a human (spec §6.3.3).
LOW_RISK_REFILL_CLASSES: frozenset[MedicationClass] = frozenset(
    {MedicationClass.STATIN, MedicationClass.ACE_INHIBITOR, MedicationClass.BIGUANIDE,
     MedicationClass.PROTON_PUMP_INHIBITOR}
)


__all__ = [
    "MedicationClass",
    "ControlledSchedule",
    "MedicationSpec",
    "MEDICATION_SPECS",
    "UnknownMedicationError",
    "map_medication",
    "LOW_RISK_REFILL_CLASSES",
]
