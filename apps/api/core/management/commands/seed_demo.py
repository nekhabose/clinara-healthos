"""Seed a demo tenant with data across all six phases (demo console only).

Idempotent-ish: creates a fixed demo organization + users, then drives the real service
layer to produce a spread of results, refills, messages, a deployed rule, and feedback so
every console tab has something to show. Run with the demo settings:

    DJANGO_SETTINGS_MODULE=clinara.settings.demo python manage.py seed_demo
"""
from __future__ import annotations

import os
import uuid

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand

from clinara.middleware.phi_safe_logging import correlation_id
from clinara.middleware.tenant import current_tenant_id, set_db_tenant

DEMO_TENANT = "11111111-1111-1111-1111-111111111111"
# The seeded account password. Overridable via the environment so a hosted deployment can set
# a real credential (the console login is credentialed username + password) without editing code.
DEMO_PASSWORD = os.environ.get("CLINARA_DEMO_PASSWORD", "demo12345")


class Command(BaseCommand):
    help = "Seed a demo tenant with sample data for the console."

    def handle(self, *args, **options):
        User = get_user_model()
        current_tenant_id.set(DEMO_TENANT)
        correlation_id.set(str(uuid.uuid4()))
        set_db_tenant(DEMO_TENANT)

        for username, role in [("clinician", "clinician"), ("programmer", "clinical_programmer"),
                               ("nurse", "nurse"), ("analyst", "operations_analyst"),
                               ("admin", "tenant_administrator")]:
            user, created = User.objects.get_or_create(
                username=username, defaults={"organization_id": DEMO_TENANT, "role": role}
            )
            user.organization_id = DEMO_TENANT
            user.role = role
            user.set_password(DEMO_PASSWORD)
            user.save()
        self.stdout.write(self.style.SUCCESS(f"Users ready (password: {DEMO_PASSWORD})"))

        self._seed_results()
        self._seed_refills()
        self._seed_messages()
        self._seed_rule_studio()
        self._seed_feedback_and_analytics()
        self.stdout.write(self.style.SUCCESS("Demo data seeded. Tenant: " + DEMO_TENANT))

    # ---- Results Intelligence ----
    def _seed_results(self):
        from domains.integrations import services as integrations

        cases = [
            {"code": "4548-4", "value": 7.8, "unit": "%", "patient": "P-1001",
             "facts": {"patient.has_diabetes": True}},
            {"code": "4548-4", "value": 9.6, "unit": "%", "patient": "P-1002",
             "facts": {"patient.has_diabetes": True}},
            {"code": "2823-3", "value": 6.8, "unit": "mmol/L", "patient": "P-1003"},
            {"code": "13457-7", "value": 165, "unit": "mg/dL", "patient": "P-1004"},
            {"code": "2345-7", "value": 92, "unit": "mg/dL", "patient": "P-1005"},
        ]
        for c in cases:
            integrations.ingest_and_process(
                tenant_id=DEMO_TENANT,
                payload={
                    "patient_external_id": c["patient"], "code_system": "LOINC",
                    "code": c["code"], "value": c["value"], "unit": c["unit"],
                    "observed_at": "2026-07-14T09:00:00+00:00",
                    "patient_facts": c.get("facts", {}), "specialty": "primary_care",
                },
            )
        self.stdout.write("  · results seeded")

    # ---- Refills ----
    def _seed_refills(self):
        from domains.refills import services as refills
        from domains.refills.models import ClientMonitoringPolicy

        ClientMonitoringPolicy.objects.get_or_create(
            tenant_id=DEMO_TENANT, med_class="statin", defaults={"auto_approve": True}
        )
        for code, dose, patient in [("617314", "10 MG", "P-1001"), ("1049221", "5 MG", "P-1002"),
                                    ("860975", "500 MG", "P-1003")]:
            refills.process_refill_request(
                tenant_id=DEMO_TENANT,
                payload={"patient_external_id": patient, "code_system": "RXNORM", "code": code,
                         "requested_dose": dose, "days_since_last_fill": 80, "days_supply": 90},
            )
        self.stdout.write("  · refills seeded")

    # ---- Patient messages ----
    def _seed_messages(self):
        from domains.messages import services as messages

        texts = [
            "I have severe chest pain and can't breathe",
            "I have a question about my bill and insurance copay",
            "I've had a fever and a cough for three days",
            "Can I get a refill on my blood pressure medication?",
        ]
        for i, text in enumerate(texts):
            messages.process_message(
                tenant_id=DEMO_TENANT,
                payload={"patient_external_id": f"P-100{i + 1}", "text": text},
            )
        self.stdout.write("  · messages seeded")

    # ---- Rule Studio ----
    def _seed_rule_studio(self):
        from domains.protocols import services as protocols
        from domains.protocols.models import Protocol

        if Protocol.objects.filter(tenant_id=DEMO_TENANT, key="a1c-mgmt").exists():
            return
        protocol = protocols.create_protocol(
            tenant_id=DEMO_TENANT, key="a1c-mgmt", marker="hemoglobin_a1c",
            title="A1C management", actor="programmer",
        )
        version = protocols.create_version(
            tenant_id=DEMO_TENANT, protocol_id=str(protocol.id), author="programmer",
            rule_body={
                "id": "a1c_above_target", "version": 1, "marker": "hemoglobin_a1c",
                "scope": {"specialties": ["primary_care"]},
                "when": {"all": [
                    {"fact": "patient.has_diabetes", "operator": "equals", "value": True},
                    {"fact": "lab.a1c", "operator": "greater_than_or_equal", "value": 7.0},
                ]},
                "then": {"classification": "clinician_review_required",
                         "recommended_action": "evaluate_current_plan",
                         "reason_codes": ["A1C_ABOVE_CONFIGURED_TARGET"]},
                "safety": {"excluded_when": ["patient.pregnancy"]},
            },
        )
        protocols.add_test_case(
            tenant_id=DEMO_TENANT, version_id=str(version.id), name="above_target",
            marker="hemoglobin_a1c", specialty="primary_care",
            facts={"lab.a1c": 7.8, "patient.has_diabetes": True},
            expected_classification="clinician_review_required",
        )
        protocols.simulate(tenant_id=DEMO_TENANT, version_id=str(version.id))
        protocols.analyze_impact(tenant_id=DEMO_TENANT, version_id=str(version.id))
        protocols.submit_for_review(tenant_id=DEMO_TENANT, version_id=str(version.id))
        protocols.approve(tenant_id=DEMO_TENANT, version_id=str(version.id),
                          actor="programmer", role="clinical")
        protocols.approve(tenant_id=DEMO_TENANT, version_id=str(version.id),
                          actor="eng_lead", role="engineering")
        protocols.deploy(tenant_id=DEMO_TENANT, version_id=str(version.id),
                         mode="shadow", actor="eng_lead")
        self.stdout.write("  · rule studio seeded")

    # ---- Feedback + analytics ----
    def _seed_feedback_and_analytics(self):
        from domains.feedback import services as feedback

        for _ in range(4):
            feedback.capture(
                tenant_id=DEMO_TENANT, workflow_type="results", workflow_id=str(uuid.uuid4()),
                practitioner="clinician", action="edit",
                original_text="Your recent result was above target. Your care team will review "
                              "this and contact you about next steps.",
                edited_text="Your result is a bit high; we'll follow up.",
            )
        for action in ("approve", "approve", "approve", "override"):
            feedback.capture(
                tenant_id=DEMO_TENANT, workflow_type="results", workflow_id=str(uuid.uuid4()),
                practitioner="clinician", action=action,
            )
        self.stdout.write("  · feedback seeded")
