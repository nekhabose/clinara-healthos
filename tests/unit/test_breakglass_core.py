"""Break-glass access core (GA hardening — spec §10.2).

Django-free; runs with PYTHONPATH=apps/api. Clock is injected so decisions are deterministic.
"""
from domains.identity import breakglass


def test_valid_request_is_granted():
    d = breakglass.request_grant("responder@clinara", "SEV1 outage triage", ttl_seconds=900)
    assert d.granted is True


def test_missing_reason_is_refused():
    assert breakglass.request_grant("r", "", ttl_seconds=900).granted is False
    assert breakglass.request_grant("r", "   ", ttl_seconds=900).granted is False


def test_missing_responder_is_refused():
    assert breakglass.request_grant("", "reason", ttl_seconds=900).granted is False


def test_nonpositive_ttl_is_refused():
    assert breakglass.request_grant("r", "reason", ttl_seconds=0).granted is False
    assert breakglass.request_grant("r", "reason", ttl_seconds=-5).granted is False


def test_ttl_over_cap_is_refused():
    d = breakglass.request_grant("r", "reason", ttl_seconds=breakglass.MAX_TTL_SECONDS + 1)
    assert d.granted is False
    assert "cap" in d.reason


def test_grant_active_within_window():
    g = breakglass.BreakGlassGrant("r", "reason", granted_at=1000, ttl_seconds=900)
    assert breakglass.is_active(g, now=1000) is True
    assert breakglass.is_active(g, now=1450) is True
    assert breakglass.is_active(g, now=1900) is True  # exactly at expiry boundary


def test_grant_inactive_after_expiry():
    g = breakglass.BreakGlassGrant("r", "reason", granted_at=1000, ttl_seconds=900)
    assert breakglass.is_active(g, now=1901) is False


def test_grant_inactive_before_start():
    g = breakglass.BreakGlassGrant("r", "reason", granted_at=1000, ttl_seconds=900)
    assert breakglass.is_active(g, now=999) is False


def test_revoked_grant_is_inactive_even_within_window():
    g = breakglass.BreakGlassGrant("r", "reason", granted_at=1000, ttl_seconds=900, revoked=True)
    assert breakglass.is_active(g, now=1100) is False
