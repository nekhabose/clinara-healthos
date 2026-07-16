"""Phase 10 — Specialty Protocol Breadth (closes gaps.md G6).

Two layers: the pure pack mechanics (load / bind / validate / coverage — no DB) and the
governed service layer (per-tenant threshold policy, gated customization, tenant-isolated
rule resolution). The through-line is the §1 invariant: breadth is deterministic DATA over the
existing engine, never a model-driven decision, and a customization can never weaken safety.
"""
import uuid

import pytest
from clinara_protocol_engine import Rule, critical_breach, evaluate
from clinara_terminology import CanonicalMarker

from domains.protocols.core import (
    SafetyViolation,
    Scenario,
    assert_cannot_weaken_safety,
    snapshot_from_scenario,
)
from domains.specialties import core, services
from domains.specialties.catalog import AMBULATORY_SPECIALTIES, specialty_keys
from domains.specialties.models import SpecialtyThresholdPolicy

# --------------------------------------------------------------------------------------
# Pure pack mechanics — no DB
# --------------------------------------------------------------------------------------

def test_every_pack_passes_the_activation_gate():
    """Exit gate: each pack binds, passes its required tests, and weakens no critical."""
    validations = services.validate_all()
    assert validations, "expected specialty packs"
    for v in validations:
        assert v.ok, f"pack {v.specialty} failed gate: {v.errors}"
        assert v.safety_ok
        assert v.all_tests_passed
        assert v.test_total >= 1  # required test cases exist


def test_registry_covers_30_plus_ambulatory_specialties():
    report = services.coverage_report()
    assert report["registered"] >= 30
    assert report["uncovered"] == []
    assert report["covered"] == report["registered"]


def test_bind_parameters_substitutes_placeholders_deterministically():
    node = {"when": {"all": [{"fact": "lab.tsh", "operator": "greater_than",
                             "value": {"param": "tsh_upper"}}]}}
    used: dict = {}
    bound = core.bind_parameters(node, {"tsh_upper": 4.5}, used)
    assert bound["when"]["all"][0]["value"] == 4.5
    assert used == {"tsh_upper": 4.5}
    # Deterministic: same inputs → identical structure.
    assert core.bind_parameters(node, {"tsh_upper": 4.5}) == bound


def test_bind_parameters_fails_loud_on_unbound_parameter():
    with pytest.raises(core.ParameterError):
        core.bind_parameters({"value": {"param": "does_not_exist"}}, {})


def test_resolve_parameters_rejects_undeclared_override():
    pack = services.pack_for_specialty("thyroid")
    with pytest.raises(core.ParameterError):
        core.resolve_parameters(pack, {"not_a_param": 1.0})


def test_no_pack_rule_can_downclassify_a_critical_value():
    """For every pack rule marker with a critical band, a critical value never matches a
    non-critical pack rule (the engine escalates it first, and the guard holds)."""
    critical_probe = {
        CanonicalMarker.SODIUM: 115.0, CanonicalMarker.CALCIUM: 14.0,
        CanonicalMarker.HEMOGLOBIN: 5.0, CanonicalMarker.PLATELETS: 10.0,
        CanonicalMarker.WBC: 60.0, CanonicalMarker.INR: 6.0,
    }
    for pack in services.packs():
        rules = core.pack_rules(pack)
        for rule in rules:
            marker = CanonicalMarker(rule.marker)
            if marker not in critical_probe:
                continue
            value = critical_probe[marker]
            assert critical_breach(marker, value) is not None
            scenario = Scenario(name="crit", marker=marker,
                                facts={rule_alias(marker): value})
            # Must not raise: the rule cannot claim a non-critical outcome for a critical value.
            assert_cannot_weaken_safety(rule, [scenario])


def test_the_safety_guard_actually_bites_on_a_crafted_bad_rule():
    """A hand-crafted rule that claims a non-critical outcome for a critical value is refused —
    proof the guard is real, not vacuous."""
    bad = Rule.model_validate({
        "id": "bad_hemoglobin", "version": 1, "marker": "hemoglobin",
        "when": {"all": [{"fact": "lab.hemoglobin", "operator": "less_than", "value": 8.0}]},
        "then": {"classification": "routine_follow_up"},
    })
    critical_scenario = Scenario(name="crit", marker=CanonicalMarker.HEMOGLOBIN,
                                 facts={"lab.hemoglobin": 5.0})
    with pytest.raises(SafetyViolation):
        assert_cannot_weaken_safety(bad, [critical_scenario])


def rule_alias(marker: CanonicalMarker) -> str:
    from clinara_terminology import LAB_FACT_ALIAS
    return LAB_FACT_ALIAS[marker]


def test_per_tenant_threshold_changes_the_engine_decision_no_code_change():
    """The exit gate, proven at the engine: the SAME snapshot yields a DIFFERENT governed
    decision under two threshold policies — purely from data, no rule YAML or code edited."""
    pack = services.pack_for_specialty("thyroid")
    snapshot = snapshot_from_scenario(
        Scenario(name="tsh", marker=CanonicalMarker.TSH,
                 facts={"lab.tsh": 4.2}, specialty="endocrinology")
    )
    default_rules = core.pack_rules(pack)                       # tsh_upper = 4.5 (default)
    tighter_rules = core.pack_rules(pack, {"tsh_upper": 4.0})   # practice runs a tighter target

    default = evaluate(snapshot, marker=CanonicalMarker.TSH, rules=default_rules,
                       specialty="endocrinology")
    tighter = evaluate(snapshot, marker=CanonicalMarker.TSH, rules=tighter_rules,
                       specialty="endocrinology")

    assert default.decision.classification.value == "normal"
    assert tighter.decision.classification.value == "routine_follow_up"


# --------------------------------------------------------------------------------------
# Governed service layer — DB-backed (each test opts in with @pytest.mark.django_db)
# --------------------------------------------------------------------------------------


@pytest.fixture
def tenant() -> str:
    return str(uuid.uuid4())


@pytest.mark.django_db
def test_set_threshold_persists_and_resolve_rules_reflects_it(tenant):
    services.set_threshold(tenant_id=tenant, specialty="thyroid",
                           parameter="tsh_upper", value=4.0, actor="dr-endo")
    assert services.effective_thresholds(tenant, "thyroid")["tsh_upper"] == 4.0

    rules = services.resolve_rules(tenant, "endocrinology")
    tsh_rule = next(r for r in rules if r.id == "tsh_subclinical_hypothyroid")
    # The bound rule carries the overridden literal (no placeholder, no code change).
    lower_bound = tsh_rule.when.all[0].value
    assert lower_bound == 4.0
    # Base Phase 1 rules are still present in the composed set.
    assert any(r.id == "a1c_above_target" for r in rules)


@pytest.mark.django_db
def test_set_threshold_rejects_an_override_that_breaks_a_required_test(tenant):
    # tsh_upper = 7.0 makes the subclinical test case (tsh=6.5) stop flagging → gate fails.
    with pytest.raises(services.ThresholdRejected):
        services.set_threshold(tenant_id=tenant, specialty="thyroid",
                               parameter="tsh_upper", value=7.0, actor="dr-endo")
    # Nothing was persisted.
    assert SpecialtyThresholdPolicy.objects.filter(tenant_id=tenant).count() == 0


@pytest.mark.django_db
def test_set_threshold_rejects_an_undeclared_parameter(tenant):
    with pytest.raises(services.ThresholdRejected):
        services.set_threshold(tenant_id=tenant, specialty="thyroid",
                               parameter="not_a_real_param", value=1.0)


@pytest.mark.django_db
def test_threshold_policy_is_tenant_isolated(tenant):
    other = str(uuid.uuid4())
    services.set_threshold(tenant_id=tenant, specialty="thyroid",
                           parameter="tsh_upper", value=4.0)
    # The other tenant sees pack defaults, never this tenant's override.
    assert services.effective_thresholds(other, "thyroid")["tsh_upper"] == 4.5
    assert services.get_overrides(other, "thyroid") == {}


@pytest.mark.django_db
def test_reset_thresholds_returns_to_pack_defaults(tenant):
    services.set_threshold(tenant_id=tenant, specialty="thyroid",
                           parameter="tsh_upper", value=4.0)
    services.reset_thresholds(tenant_id=tenant, specialty="thyroid", actor="dr-endo")
    assert services.effective_thresholds(tenant, "thyroid")["tsh_upper"] == 4.5


@pytest.mark.django_db
def test_end_to_end_two_tenants_get_different_classifications(tenant):
    """Through the real ingest pipeline: same TSH result, two practices, different governed
    outcome — because one practice customized its threshold. No code change between them."""
    from domains.integrations import services as integrations

    other = str(uuid.uuid4())
    services.set_threshold(tenant_id=other, specialty="thyroid",
                           parameter="tsh_upper", value=4.0, actor="dr-endo")

    payload = {
        "patient_external_id": "P-TSH", "code_system": "LOINC", "code": "3016-3",
        "value": 4.2, "unit": "mIU/L", "observed_at": "2026-07-10T09:00:00+00:00",
        "patient_facts": {}, "specialty": "endocrinology",
    }
    _, wf_default, _ = integrations.ingest_and_process(tenant_id=tenant, payload=payload)
    _, wf_tight, _ = integrations.ingest_and_process(tenant_id=other, payload=payload)

    assert wf_default.classification == "normal"
    assert wf_tight.classification == "routine_follow_up"


@pytest.mark.django_db
def test_list_specialties_reports_full_coverage(tenant):
    listed = services.list_specialties()
    assert len(listed) == len(AMBULATORY_SPECIALTIES)
    assert all(entry["covered"] for entry in listed)
    assert len(specialty_keys()) >= 30
