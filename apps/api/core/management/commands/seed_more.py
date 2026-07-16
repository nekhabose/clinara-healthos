"""Enrich the demo tenant with a fuller spread of data across every role's surfaces.

Additive and idempotent: uses a distinct patient-id range (P-2xxx) and distinct protocol keys
so it never collides with the base ``seed_demo`` data. The ingest-based blocks (results,
messages, refills, feedback) are guarded by a sentinel so re-running does not duplicate them;
the coding / integrations / retention blocks are naturally idempotent (upsert / get_or_create).

    DJANGO_SETTINGS_MODULE=clinara.settings.vercel python manage.py seed_more

Fills, per role:
- clinician / nurse : more lab results across lanes (critical → normal), more patient messages
  (emergency → billing), more refills (auto-approve → human-routed).
- clinician         : coding / billing suggestions (documented-uncoded + HCC gap).
- programmer        : more protocols in varied lifecycle states (draft / in-review / deployed).
- analyst           : a richer feedback stream (approve / edit / override) for the dashboards.
- admin             : EHR integrations (connected / degraded) + a retention policy.
"""
from __future__ import annotations

import uuid

from django.core.management.base import BaseCommand

from clinara.middleware.phi_safe_logging import correlation_id
from clinara.middleware.tenant import current_tenant_id, set_db_tenant

DEMO_TENANT = "11111111-1111-1111-1111-111111111111"
SENTINEL_PATIENT = "P-2001"


class Command(BaseCommand):
    help = "Add a fuller spread of demo data across every role's surfaces (additive, idempotent)."

    def handle(self, *args, **options):
        current_tenant_id.set(DEMO_TENANT)
        correlation_id.set(str(uuid.uuid4()))
        set_db_tenant(DEMO_TENANT)

        self._seed_protocols()        # programmer
        self._seed_coding()           # clinician
        self._seed_integrations()     # admin
        self._seed_retention()        # admin

        from domains.messages.models import PatientMessage

        already = PatientMessage.objects.filter(
            tenant_id=DEMO_TENANT, patient_external_id=SENTINEL_PATIENT
        ).exists()
        if already:
            self.stdout.write(self.style.WARNING(
                "  · ingest blocks (results/messages/refills/feedback) already seeded — skipped"))
        else:
            self._seed_results()      # clinician / nurse
            self._seed_messages()     # clinician / nurse
            self._seed_refills()      # clinician / nurse
            self._seed_feedback()     # analyst

        self.stdout.write(self.style.SUCCESS("Enrichment complete. Tenant: " + DEMO_TENANT))

    # ---------------------------------------------------------------- results
    def _seed_results(self):
        from domains.integrations import services as integrations

        # (LOINC code, value, unit, patient, extra facts) across every triage lane.
        cases = [
            ("4548-4", 11.4, "%", "P-2001", {"patient.has_diabetes": True}),   # a1c critical/high
            ("4548-4", 8.9, "%", "P-2002", {"patient.has_diabetes": True}),    # a1c high
            ("4548-4", 7.3, "%", "P-2003", {"patient.has_diabetes": True}),    # a1c review
            ("4548-4", 5.4, "%", "P-2004", {}),                                 # a1c normal
            ("2345-7", 315, "mg/dL", "P-2005", {"patient.has_diabetes": True}), # glucose high
            ("2345-7", 96, "mg/dL", "P-2006", {}),                             # glucose normal
            ("13457-7", 198, "mg/dL", "P-2007", {}),                            # ldl high
            ("13457-7", 88, "mg/dL", "P-2008", {}),                             # ldl normal
            ("2823-3", 6.6, "mmol/L", "P-2009", {}),                            # potassium critical
            ("2823-3", 4.1, "mmol/L", "P-2010", {}),                            # potassium normal
            ("4548-4", 9.8, "%", "P-2011", {"patient.has_diabetes": True}),    # a1c high
            ("2345-7", 58, "mg/dL", "P-2012", {}),                             # glucose low
        ]
        for code, value, unit, patient, facts in cases:
            integrations.ingest_and_process(
                tenant_id=DEMO_TENANT,
                payload={
                    "patient_external_id": patient, "code_system": "LOINC",
                    "code": code, "value": value, "unit": unit,
                    "observed_at": "2026-07-15T09:00:00+00:00",
                    "patient_facts": facts, "specialty": "primary_care",
                },
            )
        self.stdout.write(f"  · results: +{len(cases)}")

    # ---------------------------------------------------------------- messages
    def _seed_messages(self):
        from domains.messages import services as messages

        texts = [
            "I'm having chest pain radiating to my left arm and I feel dizzy",   # emergency
            "My blood sugar has been running high all week, over 300",           # clinical/urgent
            "Can I get a refill on my atorvastatin? I'm almost out",             # medication
            "I'd like to schedule my annual physical sometime next month",       # scheduling
            "What was my cholesterol result from last visit?",                   # results question
            "I have a question about a charge on my last statement",             # billing
            "My blood pressure cuff read 165/98 this morning, should I worry?",  # clinical
            "Thank you to Dr. Lee, the new medication is really helping",        # gratitude/admin
        ]
        for i, text in enumerate(texts):
            messages.process_message(
                tenant_id=DEMO_TENANT,
                payload={"patient_external_id": f"P-20{i + 1:02d}", "text": text},
            )
        self.stdout.write(f"  · messages: +{len(texts)}")

    # ---------------------------------------------------------------- refills
    def _seed_refills(self):
        from domains.refills import services as refills
        from domains.refills.models import ClientMonitoringPolicy

        ClientMonitoringPolicy.objects.get_or_create(
            tenant_id=DEMO_TENANT, med_class="statin", defaults={"auto_approve": True}
        )
        cases = [
            ("617314", "20 MG", "P-2001", 80, 90),    # atorvastatin (statin, auto)
            ("860975", "1000 MG", "P-2002", 75, 90),  # metformin
            ("1049221", "10 MG", "P-2003", 60, 90),   # lisinopril
            ("197361", "50 MG", "P-2005", 85, 90),    # losartan
            ("311036", "40 MG", "P-2007", 70, 90),    # simvastatin (statin, auto)
            ("197518", "0.5 MG", "P-2009", 20, 30),   # short supply — flagged
        ]
        for code, dose, patient, since, supply in cases:
            refills.process_refill_request(
                tenant_id=DEMO_TENANT,
                payload={"patient_external_id": patient, "code_system": "RXNORM", "code": code,
                         "requested_dose": dose, "days_since_last_fill": since,
                         "days_supply": supply},
            )
        self.stdout.write(f"  · refills: +{len(cases)}")

    # ---------------------------------------------------------------- protocols
    def _seed_protocols(self):
        from domains.protocols import services as protocols
        from domains.protocols.models import Protocol

        def rule(rule_id, threshold):
            return {
                "id": rule_id, "version": 1, "marker": "hemoglobin_a1c",
                "scope": {"specialties": ["primary_care"]},
                "when": {"all": [
                    {"fact": "patient.has_diabetes", "operator": "equals", "value": True},
                    {"fact": "lab.a1c", "operator": "greater_than_or_equal", "value": threshold},
                ]},
                "then": {"classification": "clinician_review_required",
                         "recommended_action": "evaluate_current_plan",
                         "reason_codes": ["A1C_ABOVE_CONFIGURED_TARGET"]},
                "safety": {"excluded_when": ["patient.pregnancy"]},
            }

        added = 0
        # A draft (authored, not yet submitted).
        added += self._protocol(protocols, Protocol, key="a1c-tight-control",
                                title="A1C tight control (draft)", rule=rule("a1c_tight", 6.5),
                                stage="draft")
        # In review (submitted, awaiting dual approval).
        added += self._protocol(protocols, Protocol, key="a1c-elderly-relaxed",
                                title="A1C relaxed target — elderly (in review)",
                                rule=rule("a1c_elderly", 8.0), stage="review")
        self.stdout.write(f"  · protocols: +{added} (varied states)")

    def _protocol(self, protocols, Protocol, *, key, title, rule, stage):
        if Protocol.objects.filter(tenant_id=DEMO_TENANT, key=key).exists():
            return 0
        try:
            p = protocols.create_protocol(tenant_id=DEMO_TENANT, key=key,
                                          marker="hemoglobin_a1c", title=title, actor="programmer")
            v = protocols.create_version(tenant_id=DEMO_TENANT, protocol_id=str(p.id),
                                         author="programmer", rule_body=rule)
            protocols.add_test_case(
                tenant_id=DEMO_TENANT, version_id=str(v.id), name="above_target",
                marker="hemoglobin_a1c", specialty="primary_care",
                facts={"lab.a1c": rule["when"]["all"][1]["value"] + 0.5,
                       "patient.has_diabetes": True},
                expected_classification="clinician_review_required",
            )
            protocols.simulate(tenant_id=DEMO_TENANT, version_id=str(v.id))
            if stage == "review":
                protocols.submit_for_review(tenant_id=DEMO_TENANT, version_id=str(v.id))
            return 1
        except Exception as exc:  # a validation quirk shouldn't abort the whole seed
            self.stdout.write(self.style.WARNING(f"    protocol {key} skipped: {exc}"))
            return 0

    # ---------------------------------------------------------------- coding
    def _seed_coding(self):
        from domains.coding import catalog as ccat
        from domains.coding import core as ccore
        from domains.coding import services as coding

        n = 0
        try:
            # HCC gap — A1c at/above the diabetes threshold with no diabetes coded.
            n += len(coding.analyze_encounter(
                tenant_id=DEMO_TENANT, patient_external_id="P-3001", encounter_id="ENC-3001",
                lab_values={ccat.MARKER_A1C: 7.9}, facts={"patient.has_diabetes": True},
                encounter_dx=[], problem_list=[],
            ))
            # Documented-but-uncoded — active problem not on the encounter.
            n += len(coding.analyze_encounter(
                tenant_id=DEMO_TENANT, patient_external_id="P-3002", encounter_id="ENC-3002",
                problem_list=[ccore.ProblemListItem(
                    description="Type 2 diabetes mellitus", code="E11.9", status="active")],
                encounter_dx=[], lab_values={ccat.MARKER_A1C: 8.4},
                facts={"patient.has_diabetes": True},
            ))
        except Exception as exc:
            self.stdout.write(self.style.WARNING(f"    coding skipped: {exc}"))
        self.stdout.write(f"  · coding suggestions: {n}")

    # ---------------------------------------------------------------- integrations
    def _seed_integrations(self):
        from domains.integrations.models import Integration

        rows = [
            ("Epic — Main Clinic", "fhir", "Epic", "connected"),
            ("athenahealth — Cardiology", "fhir", "athenahealth", "connected"),
            ("Quest Diagnostics — HL7 feed", "hl7v2", "Quest", "degraded"),
        ]
        n = 0
        for name, kind, source, status in rows:
            _, created = Integration.objects.get_or_create(
                tenant_id=DEMO_TENANT, name=name,
                defaults={"kind": kind, "source_system": source, "status": status},
            )
            n += int(created)
        self.stdout.write(f"  · integrations: +{n}")

    # ---------------------------------------------------------------- retention
    def _seed_retention(self):
        from domains.retention import services as retention

        try:
            retention.set_retention_window(
                tenant_id=DEMO_TENANT, category="raw_inbound", days=90, actor="admin")
            retention.set_retention_window(
                tenant_id=DEMO_TENANT, category="patient_messages", days=90, actor="admin")
            self.stdout.write("  · retention policy: set")
        except Exception as exc:
            self.stdout.write(self.style.WARNING(f"    retention skipped: {exc}"))

    # ---------------------------------------------------------------- feedback
    def _seed_feedback(self):
        from domains.feedback import services as feedback

        plan = [
            ("results", "approve", 9), ("results", "edit", 4), ("results", "override", 3),
            ("messages", "approve", 6), ("messages", "edit", 2), ("messages", "override", 1),
            ("refills", "approve", 7), ("refills", "override", 2),
        ]
        total = 0
        for wtype, action, count in plan:
            for _ in range(count):
                kwargs = dict(
                    tenant_id=DEMO_TENANT, workflow_type=wtype, workflow_id=str(uuid.uuid4()),
                    practitioner="clinician", action=action,
                )
                if action == "edit":
                    kwargs["original_text"] = ("Your recent result was above target. Your care "
                                               "team will review this and contact you.")
                    kwargs["edited_text"] = "Your result is a little high; we'll follow up soon."
                feedback.capture(**kwargs)
                total += 1
        self.stdout.write(f"  · feedback: +{total}")
