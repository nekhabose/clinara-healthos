"""Pure retry/backoff policy (plan Phase 7)."""
import pytest
from clinara_integration_sdk import NO_RETRY, RetryPolicy


def test_first_attempt_is_immediate():
    assert RetryPolicy().backoff(1) == 0.0


def test_backoff_grows_exponentially_and_caps():
    p = RetryPolicy(base_delay_seconds=0.5, multiplier=2.0, max_delay_seconds=8.0)
    assert p.backoff(2) == 0.5
    assert p.backoff(3) == 1.0
    assert p.backoff(4) == 2.0
    assert p.backoff(10) == 8.0  # capped


def test_should_retry_only_when_retryable_and_attempts_remain():
    p = RetryPolicy(max_attempts=3)
    assert p.should_retry(1, retryable=True) is True
    assert p.should_retry(2, retryable=True) is True
    assert p.should_retry(3, retryable=True) is False  # last attempt
    assert p.should_retry(1, retryable=False) is False  # terminal error


def test_no_retry_policy_allows_single_attempt():
    assert NO_RETRY.max_attempts == 1
    assert NO_RETRY.should_retry(1, retryable=True) is False


def test_invalid_max_attempts_rejected():
    with pytest.raises(ValueError):
        RetryPolicy(max_attempts=0)
