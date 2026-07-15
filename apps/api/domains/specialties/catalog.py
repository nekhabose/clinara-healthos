"""Ambulatory specialty registry (plan Phase 10 — Specialty Protocol Breadth, closes G6).

The codified list of ambulatory specialties Clinara claims to support, as DATA (the same way
``clinara_terminology.MARKER_SPECS`` codifies markers and ``domains/coding/catalog`` codifies
coding content). Elaborate advertises "rules-based protocols across 30+ ambulatory
specialties"; this registry is the enumerated set, and the coverage guarantee
(``core.coverage``) asserts every entry here is served by at least one active protocol-pack
rule — so "30+ specialties" is a *tested* claim, not a marketing one.

Each specialty is served by one or more parameterized protocol packs (``clinical/protocols/
specialties/*.yaml``) whose ``scope.specialties`` lists it. Growing breadth is a content +
clinical-validation effort through the Rule Studio, never an engine change (plan Phase 10).
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Specialty:
    key: str
    display_name: str
    # Human-facing note on the clinical panels this specialty typically monitors.
    panels: tuple[str, ...]


# 34 ambulatory specialties (> the "30+" parity bar). Keys are the canonical strings threaded
# through ``scope.specialties``, ``User.specialties``, and the context snapshot.
AMBULATORY_SPECIALTIES: dict[str, Specialty] = {
    s.key: s
    for s in (
        Specialty("primary_care", "Primary Care", ("glycemic", "lipids", "renal", "thyroid")),
        Specialty("family_medicine", "Family Medicine", ("glycemic", "lipids", "hepatic")),
        Specialty("internal_medicine", "Internal Medicine", ("metabolic", "hepatic", "heme")),
        Specialty("endocrinology", "Endocrinology", ("glycemic", "thyroid", "lipids")),
        Specialty("cardiology", "Cardiology", ("lipids", "renal", "coagulation")),
        Specialty("nephrology", "Nephrology", ("renal", "electrolytes")),
        Specialty("gastroenterology", "Gastroenterology", ("hepatic",)),
        Specialty("hepatology", "Hepatology", ("hepatic",)),
        Specialty("pulmonology", "Pulmonology", ("inflammatory",)),
        Specialty("rheumatology", "Rheumatology", ("inflammatory", "hepatic", "heme")),
        Specialty("hematology", "Hematology", ("heme", "coagulation")),
        Specialty("medical_oncology", "Medical Oncology", ("heme", "hepatic")),
        Specialty("infectious_disease", "Infectious Disease", ("inflammatory", "hepatic")),
        Specialty("neurology", "Neurology", ("coagulation",)),
        Specialty("dermatology", "Dermatology", ("hepatic",)),
        Specialty("allergy_immunology", "Allergy & Immunology", ("heme", "inflammatory")),
        Specialty("geriatrics", "Geriatrics", ("thyroid", "heme", "renal")),
        Specialty("obstetrics", "Obstetrics", ("thyroid", "heme")),
        Specialty("gynecology", "Gynecology", ("heme",)),
        Specialty("urology", "Urology", ("renal",)),
        Specialty("psychiatry", "Psychiatry", ("thyroid", "electrolytes")),
        Specialty("sports_medicine", "Sports Medicine", ("heme",)),
        Specialty("pain_management", "Pain Management", ("hepatic",)),
        Specialty("sleep_medicine", "Sleep Medicine", ("thyroid",)),
        Specialty("obesity_medicine", "Obesity Medicine", ("glycemic", "lipids")),
        Specialty("preventive_medicine", "Preventive Medicine", ("lipids",)),
        Specialty("vascular_medicine", "Vascular Medicine", ("lipids", "coagulation")),
        Specialty("lipidology", "Lipidology", ("lipids",)),
        Specialty("transplant_nephrology", "Transplant Nephrology", ("renal",)),
        Specialty("womens_health", "Women's Health", ("thyroid", "heme")),
        Specialty("mens_health", "Men's Health", ("thyroid", "lipids")),
        Specialty("otolaryngology", "Otolaryngology (ENT)", ("thyroid",)),
        Specialty("ophthalmology", "Ophthalmology", ("thyroid",)),
        Specialty("podiatry", "Podiatry", ("inflammatory",)),
    )
}


def specialty_keys() -> list[str]:
    return list(AMBULATORY_SPECIALTIES.keys())
