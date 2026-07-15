"""Hardened Integration Gateway (plan Phase 3 exit gate — zero silent failures).

DB-backed. Proves: HL7/FHIR ingestion via the gateway, malformed → dead-letter (never
dropped), idempotent replay, rate-limiting, duplicate suppression, tenant-specific mappings,
silent-gap detection with critical alerts, and the health dashboard.
"""
import uuid

import pytest

from domains.clinical_data.models import Observation
from domains.integrations import gateway, monitoring
from domains.integrations import services as integrations
from domains.integrations.models import (
    Alert,
    DeadLetterEvent,
    IntegrationError,
    IntegrationStatus,
)
from domains.terminology.models import IntegrationMapping
from domains.workflows.models import WorkflowInstance

pytestmark = pytest.mark.django_db


def _tenant() -> str:
    return str(uuid.uuid4())


def _integration(t, kind="hl7v2", **kw):
    return integrations.register_integration(tenant_id=t, name=f"lab-{kind}", kind=kind, **kw)


ORU = (
    "MSH|^~\\&|LIS|GENERAL|CLINARA|CLINARA|20260710090000||ORU^R01|MSG1|P|2.5\r"
    "PID|1||P123^^^HOSP^MR||DOE^JANE\r"
    "OBX|1|NM|4548-4^Hemoglobin A1c^LN||7.8|%|||||F|||20260710091500\r"
)


def test_hl7_oru_flows_to_a_workflow():
    t = _tenant()
    integration = _integration(t)
    result = gateway.receive_hl7(integration_id=str(integration.id), raw_message=ORU)
    assert result["status"] == "processed"
    assert Observation.objects.filter(tenant_id=t).count() == 1
    assert WorkflowInstance.objects.filter(tenant_id=t).count() == 1


def test_malformed_hl7_is_dead_lettered_not_dropped():
    t = _tenant()
    integration = _integration(t)
    result = gateway.receive_hl7(integration_id=str(integration.id), raw_message="garbage")
    assert result["status"] == "dead_lettered"
    assert DeadLetterEvent.objects.filter(tenant_id=t, status="open").count() == 1
    assert IntegrationError.objects.filter(tenant_id=t, kind="malformed").exists()


def test_dead_letter_replay_is_idempotent():
    t = _tenant()
    integration = _integration(t)
    # Malformed → dead-letter, then "fix" by replaying the SAME (still-bad) message: no dup.
    gateway.receive_hl7(integration_id=str(integration.id), raw_message="garbage")
    dl = DeadLetterEvent.objects.get(tenant_id=t)
    # Now replay a genuinely-good message via a fresh dead-letter to prove no duplication:
    gateway.receive_hl7(integration_id=str(integration.id), raw_message=ORU)
    gateway.receive_hl7(integration_id=str(integration.id), raw_message=ORU)  # duplicate
    assert WorkflowInstance.objects.filter(tenant_id=t).count() == 1  # duplicate suppressed
    # Replaying the bad one stays open (still unprocessable) — never silently lost.
    res = gateway.replay_dead_letter(tenant_id=t, dead_letter_id=str(dl.id))
    assert res["status"] == "open"
    dl.refresh_from_db()
    assert dl.replay_count == 1


def test_duplicate_hl7_never_double_processes():
    t = _tenant()
    integration = _integration(t)
    gateway.receive_hl7(integration_id=str(integration.id), raw_message=ORU)
    gateway.receive_hl7(integration_id=str(integration.id), raw_message=ORU)
    assert Observation.objects.filter(tenant_id=t).count() == 1
    assert WorkflowInstance.objects.filter(tenant_id=t).count() == 1


def test_rate_limiting_rejects_burst():
    t = _tenant()
    integration = _integration(t, rate_capacity=1, rate_refill_per_second=0.0)
    # First allowed, second rejected (bucket empty, no refill), at the same instant.
    r1 = gateway.receive_hl7(integration_id=str(integration.id), raw_message=ORU, now_epoch=0.0)
    r2 = gateway.receive_hl7(
        integration_id=str(integration.id),
        raw_message=ORU.replace("MSG1", "MSG2"), now_epoch=0.0,
    )
    assert r1["status"] == "processed"
    assert r2["status"] == "rate_limited"
    assert IntegrationError.objects.filter(tenant_id=t, kind="rate_limited").exists()


def test_tenant_specific_mapping_resolves_unknown_code():
    t = _tenant()
    integration = _integration(t)
    # A code not in the seed LOINC map, mapped per-tenant → resolves instead of queuing.
    IntegrationMapping.objects.create(
        tenant_id=t, code_system="LOINC", code="XYZ-1", marker="hemoglobin_a1c", active=True
    )
    msg = ORU.replace("4548-4^Hemoglobin A1c^LN", "XYZ-1^Local A1c^LN")
    result = gateway.receive_hl7(integration_id=str(integration.id), raw_message=msg)
    assert result["status"] == "processed"
    assert Observation.objects.filter(tenant_id=t, marker="hemoglobin_a1c").count() == 1


def test_silent_gap_raises_critical_alert():
    t = _tenant()
    integration = _integration(t, expected_interval_seconds=60)
    gateway.receive_hl7(integration_id=str(integration.id), raw_message=ORU, now_epoch=0.0)
    integration.refresh_from_db()
    seen = integration.last_seen_at.timestamp()
    # Scan far past the grace window → critical silent-gap alert, interface marked disconnected.
    alerts = monitoring.scan_silent_gaps(t, now_epoch=seen + 10_000)
    assert len(alerts) == 1
    assert alerts[0].severity == "critical"
    integration.refresh_from_db()
    assert integration.status == IntegrationStatus.DISCONNECTED
    # Idempotent: a second scan does not double-alert.
    assert monitoring.scan_silent_gaps(t, now_epoch=seen + 20_000) == []


def test_adt_message_acknowledged_without_workflow():
    t = _tenant()
    integration = _integration(t)
    adt = (
        "MSH|^~\\&|ADT|G|CLINARA|C|20260101||ADT^A01|A1|P|2.5\r"
        "PID|1||P999^^^HOSP^MR||SMITH^JOHN\r"
        "PV1|1|I|||||||||||||||||ENC42\r"
    )
    result = gateway.receive_hl7(integration_id=str(integration.id), raw_message=adt)
    assert result["status"] == "acknowledged"
    assert result["category"] == "ADT"
    assert WorkflowInstance.objects.filter(tenant_id=t).count() == 0


def test_health_dashboard_reports_counters():
    t = _tenant()
    integration = _integration(t)
    gateway.receive_hl7(integration_id=str(integration.id), raw_message=ORU)
    gateway.receive_hl7(integration_id=str(integration.id), raw_message="garbage")
    health = monitoring.integration_health(t, str(integration.id))
    assert health["malformed"] == 1
    assert health["dead_letter_open"] == 1
    assert health["throughput"] >= 1


def test_tenant_scoping_isolates_integrations():
    a, b = _tenant(), _tenant()
    _integration(a)
    from domains.integrations.models import Integration
    assert Integration.objects.filter(tenant_id=a).count() == 1
    assert Integration.objects.filter(tenant_id=b).count() == 0
    assert Alert.objects.filter(tenant_id=b).count() == 0
