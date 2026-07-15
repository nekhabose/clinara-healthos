"""The outbox must refuse to publish outside a transaction (no silent loss guarantee)."""
import pytest

from core.outbox import publish_event


def test_publish_requires_atomic_transaction():
    with pytest.raises(RuntimeError, match="atomic transaction"):
        publish_event(
            event_type="ObservationReceived",
            idempotency_key="k-1",
            payload={"marker": "hemoglobin_a1c"},
        )
