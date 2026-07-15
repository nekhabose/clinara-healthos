"""Golden-dataset regression for Results Intelligence (spec §13.3, plan Phase 1).

Loads clinical/golden/results_v1.yaml and runs each case through the full pipeline,
asserting the deterministic decision. This is a release gate: an unexpected change to a
historical case is a blocking failure (plan §4 universal release gate).

Runs with PYTHONPATH=apps/api.
"""
from datetime import datetime, timezone
from pathlib import Path

import pytest
import yaml

from clinara_protocol_engine import load_rules
from domains.generation.core import load_templates
from domains.workflows.core import run_result_pipeline

ROOT = Path(__file__).resolve().parents[2]
RULES = load_rules(ROOT / "clinical/protocols")
TEMPLATES = load_templates(ROOT / "clinical/templates/results.yaml")
CASES = yaml.safe_load((ROOT / "clinical/golden/results_v1.yaml").read_text())
NOW = datetime(2026, 7, 14, tzinfo=timezone.utc)


@pytest.mark.parametrize("case", CASES, ids=[c["name"] for c in CASES])
def test_golden_case(case):
    i = case["input"]
    result = run_result_pipeline(
        tenant_id="t", patient_id="p",
        system=i["system"], code=i["code"], value=i["value"], unit=i.get("unit"),
        observed_at=NOW, now=NOW, rules=RULES, templates=TEMPLATES,
        patient_facts=i.get("patient_facts"), prior_value=i.get("prior_value"),
        specialty=i.get("specialty"), conflicting_facts=i.get("conflicting_facts"),
        source_record_ids=["obs-1"],
    )
    exp = case["expect"]

    assert result.status == exp.get("status", "decided")
    if "queue_signal" in exp:
        assert result.queue_signal == exp["queue_signal"]
    if result.status != "decided":
        return

    d = result.evaluation.decision
    if "classification" in exp:
        assert d.classification.value == exp["classification"]
    if "priority" in exp:
        assert d.priority.value == exp["priority"]
    if "automation_status" in exp:
        assert d.automation_status.value == exp["automation_status"]
    if "matched_rule" in exp:
        assert result.evaluation.trace.matched_rule_id == exp["matched_rule"]
    for code in exp.get("reason_codes_include", []):
        assert code in d.reason_codes, f"{code} not in {d.reason_codes}"
    if "validation_passed" in exp:
        assert result.validation.passed is exp["validation_passed"]
    if "patient_message" in exp:
        has_msg = result.validation.final_patient_message is not None
        assert has_msg is exp["patient_message"]


def test_dataset_is_non_trivial():
    # Guard against an accidentally-emptied golden file silently passing the gate.
    assert len(CASES) >= 12
