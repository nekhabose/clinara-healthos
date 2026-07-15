"""Pure HL7 v2 adapter + gateway primitives (plan Phase 3, workstream 2)."""
import pytest
from clinara_integration_sdk import (
    Hl7ParseError,
    TokenBucket,
    detect_silent_gap,
    parse,
    to_canonical_payloads,
)

ORU = (
    "MSH|^~\\&|LIS|GENERAL|CLINARA|CLINARA|20260710090000||ORU^R01|MSG00001|P|2.5\r"
    "PID|1||P123^^^HOSP^MR||DOE^JANE||19700101|F\r"
    "PV1|1|O|||||||||||||||||ENC777\r"
    "OBR|1|||4548-4^Hemoglobin A1c^LN|||20260710090000\r"
    "OBX|1|NM|4548-4^Hemoglobin A1c^LN||7.8|%|||||F|||20260710091500\r"
    "OBX|2|NM|2823-3^Potassium^LN||4.2|mmol/L|||||F\r"
)


def test_parse_oru_extracts_message_and_observations():
    msg = parse(ORU)
    assert msg.category == "ORU"
    assert msg.trigger == "R01"
    assert msg.patient_external_id == "P123"
    assert msg.encounter_id == "ENC777"
    assert len(msg.observations) == 2


def test_oru_lowered_to_canonical_payload():
    payloads = to_canonical_payloads(parse(ORU))
    first = payloads[0]
    assert first["code_system"] == "LOINC"   # LN normalized
    assert first["code"] == "4548-4"
    assert first["value"] == 7.8
    assert first["unit"] == "%"
    assert first["observed_at"] == "2026-07-10T09:15:00+00:00"
    assert first["patient_external_id"] == "P123"


def test_obx_falls_back_to_obr_time():
    # OBX-2 has no OBX-14 datetime → inherits the OBR-7 observation time.
    payloads = to_canonical_payloads(parse(ORU))
    assert payloads[1]["observed_at"] == "2026-07-10T09:00:00+00:00"


def test_non_numeric_obx_is_skipped_not_crashed():
    msg = (
        "MSH|^~\\&|LIS|G|CLINARA|C|20260101||ORU^R01|M1|P|2.5\r"
        "PID|1||P1\r"
        "OBX|1|TX|note^Note^LN||see chart|||||F\r"
    )
    assert to_canonical_payloads(parse(msg)) == []


def test_malformed_message_raises():
    with pytest.raises(Hl7ParseError):
        parse("not an hl7 message")
    with pytest.raises(Hl7ParseError):
        parse("")


def test_adt_message_has_patient_but_no_observations():
    adt = (
        "MSH|^~\\&|ADT|G|CLINARA|C|20260101||ADT^A01|M2|P|2.5\r"
        "PID|1||P999^^^HOSP^MR||SMITH^JOHN\r"
        "PV1|1|I|||||||||||||||||ENC42\r"
    )
    msg = parse(adt)
    assert msg.category == "ADT"
    assert msg.patient_external_id == "P999"
    assert msg.observations == []


# ---- Token bucket ----

def test_token_bucket_limits_then_refills():
    bucket = TokenBucket(capacity=2, refill_per_second=1.0, last_refill=0.0)
    assert bucket.allow(now=0.0) is True
    assert bucket.allow(now=0.0) is True
    assert bucket.allow(now=0.0) is False       # capacity exhausted
    assert bucket.allow(now=1.0) is True         # 1s → +1 token


# ---- Silent-gap detection ----

def test_silent_gap_detected_after_grace_window():
    # expected every 60s, grace ×2 = 120s. 200s of silence → gap.
    assert detect_silent_gap(last_seen_epoch=0.0, now_epoch=200.0,
                             expected_interval_seconds=60) is True
    assert detect_silent_gap(last_seen_epoch=0.0, now_epoch=100.0,
                             expected_interval_seconds=60) is False


def test_never_seen_interface_is_not_a_gap():
    assert detect_silent_gap(last_seen_epoch=None, now_epoch=999.0,
                             expected_interval_seconds=60) is False
