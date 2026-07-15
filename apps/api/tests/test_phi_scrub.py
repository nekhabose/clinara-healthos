"""Unit tests for the PHI-safe logging scrubber (no DB required)."""
from clinara.middleware.phi_safe_logging import scrub


def test_redacts_phi_keys():
    out = scrub({"patient_name": "Jane Roe", "a1c": 7.4})
    assert out["patient_name"] == "[REDACTED]"
    assert out["a1c"] == 7.4  # clinical values are not PHI and must survive


def test_redacts_ssn_and_email_in_strings():
    out = scrub("contact jane@example.com ssn 123-45-6789")
    assert "jane@example.com" not in out
    assert "123-45-6789" not in out


def test_scrub_is_recursive():
    out = scrub({"outer": [{"dob": "1970-01-01", "ok": "value"}]})
    assert out["outer"][0]["dob"] == "[REDACTED]"
    assert out["outer"][0]["ok"] == "value"
