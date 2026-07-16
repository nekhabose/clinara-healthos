"""Codified data-retention schedule (plan Phase 11 — closes G7).

Elaborate's compliance posture: *"Minimal necessary data retained for 90 days; fully purged
on termination per BAA."* This module is the **deterministic, Django-free catalog** of what
Clinara stores, how long each category is kept by default, and whether the scheduled
minimization job sweeps it on a rolling window (time-series PHI) or it is purged only on
BAA termination (longer-lived reference data).

It is *data, not model output* — the same principle as ``coding/catalog.py`` and
``MARKER_SPECS``: retention behaviour is replayable and unit-testable because the schedule is
a table, not code branches. The Django service layer maps each ``category`` key here to the
concrete ORM model(s) it purges (see ``services.PURGE_TARGETS``) — this module never imports
Django, so the windows and the anti-footgun bounds can be reasoned about in isolation.

Design rules encoded here:
  * **Minimal-necessary defaults.** Raw inbound PHI (HL7/FHIR payloads, verbatim patient
    messages) defaults to a tight **90-day** window. Derived clinical records that the replay
    /decision-trace guarantee rides on keep a longer default so an audit can still reconstruct
    a recent decision, but every window is per-tenant overridable *down*.
  * **A window can never be unbounded.** ``MAX_RETENTION_DAYS`` caps every category so a
    practice cannot silently opt out of minimization by setting a decade-long window.
  * **A window can never be zero.** ``MIN_RETENTION_DAYS`` keeps in-flight work from being
    purged out from under a clinician mid-review.
"""
from __future__ import annotations

from dataclasses import dataclass

# Guard rails on any per-tenant override (enforced in ``services.set_retention_window``).
MIN_RETENTION_DAYS = 1
MAX_RETENTION_DAYS = 3650  # 10 years — a hard ceiling so "retention" stays minimal-necessary


@dataclass(frozen=True)
class RetentionCategory:
    """One purgeable data category and its default retention behaviour.

    ``windowed`` marks the rolling-window minimization set the scheduled job sweeps. Non-windowed
    categories are longer-lived reference/registry data (a patient's current medication list, a
    patient handle) that carry no rolling-time-series semantics — they are purged only on BAA
    termination, never trimmed by the daily job.
    """

    key: str
    label: str
    default_days: int
    windowed: bool
    description: str


# The canonical retention schedule. ``key`` is the stable identifier used by policy overrides,
# the purge-target registry, audit records, and the certificate of destruction.
RETENTION_CATEGORIES: tuple[RetentionCategory, ...] = (
    # --- Raw inbound PHI — tight 90-day minimal-necessary window ---
    RetentionCategory(
        "raw_inbound", "Raw inbound EHR payloads", 90, True,
        "Verbatim HL7/FHIR payloads stored on ingest before parsing (integrations).",
    ),
    RetentionCategory(
        "dead_letters", "Dead-lettered inbound payloads", 90, True,
        "Un-processable raw payloads parked for inspect/replay (integrations).",
    ),
    RetentionCategory(
        "patient_messages", "Patient-portal messages", 90, True,
        "Verbatim inbound patient messages + their triage classification/review children.",
    ),
    RetentionCategory(
        "outbound_messages", "Delivered patient/EHR messages", 90, True,
        "Outbound portal messages + EHR tasks and their delivery attempts (delivery).",
    ),
    # --- Derived clinical records — longer default so a recent decision stays replayable ---
    RetentionCategory(
        "observations", "Lab/diagnostic observations", 365, True,
        "Canonicalized lab/diagnostic values (clinical_data).",
    ),
    RetentionCategory(
        "context_snapshots", "Chart-context snapshots", 365, True,
        "Immutable per-workflow context snapshots the engine reasoned over (context).",
    ),
    RetentionCategory(
        "results_workflows", "Results workflows", 365, True,
        "Reviewable results workflows + evaluations, communications, reviews (workflows).",
    ),
    RetentionCategory(
        "refill_workflows", "Refill workflows", 365, True,
        "Reviewable refill workflows + evaluations and reviews (refills).",
    ),
    RetentionCategory(
        "coding_suggestions", "Coding suggestions", 365, True,
        "Billing/coding suggestion queue rows (coding).",
    ),
    RetentionCategory(
        "clinician_feedback", "Clinician feedback", 365, True,
        "Captured clinician actions incl. edited text used for personalization (feedback).",
    ),
    # --- Reference/registry data — termination-only (no rolling window) ---
    RetentionCategory(
        "medications", "Medication statements", 730, False,
        "A patient's current medications + allergies (refills reference data).",
    ),
    RetentionCategory(
        "patient_references", "Patient references", 730, False,
        "Internal patient handles (clinical_data). Purged on termination only.",
    ),
)

CATEGORIES_BY_KEY: dict[str, RetentionCategory] = {c.key: c for c in RETENTION_CATEGORIES}

# Minimal-necessary defaults as a plain {key: days} map (the base every policy overlays).
DEFAULT_WINDOWS: dict[str, int] = {c.key: c.default_days for c in RETENTION_CATEGORIES}


def is_known_category(key: str) -> bool:
    return key in CATEGORIES_BY_KEY


def windowed_categories() -> tuple[str, ...]:
    """Category keys the scheduled minimization job sweeps (in catalog order)."""
    return tuple(c.key for c in RETENTION_CATEGORIES if c.windowed)


def all_categories() -> tuple[str, ...]:
    """Every category key (the BAA-termination hard-purge set), in catalog order."""
    return tuple(c.key for c in RETENTION_CATEGORIES)


__all__ = [
    "MIN_RETENTION_DAYS", "MAX_RETENTION_DAYS", "RetentionCategory", "RETENTION_CATEGORIES",
    "CATEGORIES_BY_KEY", "DEFAULT_WINDOWS", "is_known_category", "windowed_categories",
    "all_categories",
]
