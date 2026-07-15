# Clinara HealthOS
## Product Requirements and Principal Architecture Specification

**Document type:** Product requirements document and system architecture specification  
**Product name:** Clinara HealthOS  
**Primary platform:** Personalized clinical inbox intelligence and workflow automation  
**Target users:** Health systems, ambulatory practices, clinicians, nurses, clinical informaticists, clinical operations teams, and integration teams  
**Document status:** Initial build specification  
**Version:** 1.0  
**Date:** July 2026  

---

# 1. Executive Summary

Clinara HealthOS is a healthcare workflow intelligence platform that personalizes clinical automation to the way each health system, specialty, practice, and clinician delivers care.

The initial product focuses on the clinical inbox, where clinicians receive laboratory results, patient messages, prescription refill requests, follow-up tasks, and other asynchronous work. The platform reduces manual chart review, prioritizes high-risk items, generates patient-friendly communications, supports protocol-driven decisions, and routes work to the correct clinical team.

The central platform capability is the **Clinical Context Engine**, a configurable and auditable reasoning layer that combines:

- Global clinical safety rules
- Evidence-based clinical protocols
- Health-system policies
- Specialty workflows
- Practice-level configuration
- Clinician preferences
- Patient-specific clinical context
- Integration and workflow metadata
- Clinician feedback and overrides

The platform must not operate as an unconstrained medical chatbot. Clinical decisions must be made through governed, deterministic, versioned, testable logic. Generative AI may assist with classification, summarization, extraction, and communication, but it must not independently determine high-risk clinical actions.

The platform must integrate directly with electronic health record systems through HL7 v2, FHIR, SMART on FHIR, vendor APIs, webhooks, secure file exchange, and client-specific interfaces.

The initial product will support four major modules:

1. **Results Intelligence**
2. **Patient Message Intelligence**
3. **Prescription and Refill Intelligence**
4. **Clinical Operations and Analytics**

---

# 2. Product Vision

## 2.1 Vision Statement

Build the personalization and clinical context infrastructure that allows healthcare organizations to safely automate asynchronous care workflows without forcing every clinician to practice in the same way.

## 2.2 Product Mission

Clinara HealthOS will:

- Reduce clinician inbox burden
- Improve patient response times
- Increase consistency and safety
- Personalize automation to local clinical practice
- Integrate into existing EHR workflows
- Give clinical experts direct control over clinical logic
- Make every automated decision explainable and auditable
- Scale health system operations without scaling manual review proportionally

## 2.3 Core Product Principle

**Generative AI may communicate and assist, but governed clinical logic decides.**

## 2.4 Non-Negotiable Design Principles

1. Patient safety takes priority over automation rate.
2. Every decision must be explainable.
3. Every clinical rule must be versioned.
4. Every output must be traceable to its inputs.
5. Lower-level customizations must not weaken mandatory safety constraints.
6. Clinical experts must be able to author and maintain logic without editing application code.
7. Integration failures must never be silent.
8. The system must support tenant-specific behavior without code forks.
9. Automation must degrade safely when data is unavailable.
10. Human review must remain available at every risk-sensitive point.

---

# 3. Business Objectives

## 3.1 Primary Objectives

- Reduce average clinician inbox handling time by at least 30 percent.
- Reduce after-hours inbox work by at least 25 percent.
- Achieve at least 95 percent clinician agreement on eligible low-risk workflows.
- Achieve less than 0.1 percent clinician opt-out for established workflows.
- Process routine inbound clinical events within two minutes.
- Process critical events within 30 seconds.
- Maintain zero silent loss of inbound clinical events.
- Support organization, specialty, cohort, and clinician-level personalization.
- Allow clinical teams to deploy approved rule changes without engineering code releases.
- Provide complete auditability for every patient-facing output.

## 3.2 Secondary Objectives

- Reduce unnecessary patient follow-up calls and messages.
- Improve clinician adoption of AI-assisted workflows.
- Increase patient understanding of laboratory and diagnostic results.
- Improve refill response times.
- Detect documentation and coding gaps for clinician review.
- Surface operational bottlenecks by specialty, site, and workflow.
- Reduce manual implementation and clinical QA work.
- Create reusable integration patterns across health systems.

## 3.3 Product Success Metrics

### Clinical Metrics

- Clinician full-agreement rate
- Clinician edit rate
- Clinician override rate
- Unsafe automation suppression count
- Critical escalation accuracy
- False reassurance rate
- Missed escalation rate
- Patient follow-up rate
- Workflow-specific clinical quality indicators

### Operational Metrics

- Median time to first action
- Median time to resolution
- Inbox items processed per clinician
- After-hours inbox time
- Automation eligibility rate
- Automation completion rate
- Human review rate
- Reopened workflow rate
- Routing accuracy

### Platform Metrics

- Event ingestion success rate
- Event processing latency
- Queue depth
- Mapping failure rate
- Unknown clinical code rate
- EHR write-back success rate
- Rule evaluation error rate
- LLM validation failure rate
- Configuration deployment rollback rate

---

# 4. Scope

## 4.1 In Scope

### Initial Product Scope

- Laboratory result ingestion and interpretation support
- Patient result explanation
- Result prioritization
- Clinician summary generation
- Patient message classification and triage
- Prescription refill request evaluation
- Rule authoring and configuration management
- Health system and clinician customization
- EHR integration
- Clinical operations tooling
- Audit logging
- Analytics
- Multi-tenant administration
- Observability
- Human review workflows
- LLM-assisted communication and summarization
- Safety and compliance controls

## 4.2 Out of Scope for Initial Release

- Autonomous diagnosis
- Autonomous prescribing
- Autonomous treatment initiation for high-risk conditions
- Emergency clinical care
- Real-time bedside monitoring
- Full inpatient clinical decision support
- Billing claims adjudication
- Insurance prior authorization automation
- Autonomous scheduling
- Consumer symptom checker
- Replacement of the EHR
- Direct-to-consumer medical advice outside a participating provider relationship
- Model training on identifiable customer data without explicit authorization

## 4.3 Future Expansion

- Imaging result workflows
- Pathology workflows
- Referral management
- Prior authorization
- Chronic care management
- Preventive care gap closure
- Post-discharge follow-up
- Procedure preparation
- Population health outreach
- Clinical documentation support
- Care coordination
- Patient-specific care plan automation

---

# 5. User Personas

## 5.1 Physician

Needs:

- Prioritized inbox
- Relevant chart context
- Clear recommended action
- Ability to approve, edit, override, or escalate
- Confidence that automation follows personal practice
- Minimal workflow disruption
- Transparent reasoning

## 5.2 Nurse or Triage Staff

Needs:

- Correct routing
- Urgency classification
- Structured symptom summary
- Missing information prompts
- Clear escalation criteria
- Task ownership
- Team-based workflows

## 5.3 Clinical Informaticist

Needs:

- Protocol authoring
- Rule testing
- Specialty configuration
- Client-specific customization
- Conflict detection
- Deployment approvals
- Audit trails
- Performance dashboards

## 5.4 Clinical Programmer

Needs:

- No-code or low-code rule creation
- Structured data dictionary
- Rule simulation
- Bulk mapping tools
- Regression tests
- Version comparison
- Rollback
- Gap discovery
- Feedback analysis

## 5.5 Health System Administrator

Needs:

- Tenant configuration
- User management
- Workflow enablement
- Site and specialty setup
- Performance reporting
- Governance controls
- Integration status
- Compliance evidence

## 5.6 Integration Engineer

Needs:

- Interface configuration
- Mapping tools
- Test harness
- Message replay
- Error queues
- Endpoint health
- Implementation diagnostics
- Data quality reports

## 5.7 Patient

Needs:

- Clear explanations
- Timely responses
- Appropriate next steps
- Easy-to-understand language
- Safety warnings
- Communication through existing patient channels
- No contradictory messages

## 5.8 Compliance and Security Reviewer

Needs:

- Access logs
- Data lineage
- Rule lineage
- Model usage records
- Retention controls
- Tenant isolation
- Approval records
- Incident evidence

---

# 6. Functional Modules

# 6.1 Results Intelligence

## 6.1.1 Objective

Help clinicians review, prioritize, explain, and act on laboratory and diagnostic results.

## 6.1.2 Supported Result Types

Initial release:

- Hemoglobin A1C
- Fasting glucose
- Random glucose
- LDL
- HDL
- Triglycerides
- Total cholesterol
- TSH
- Free T4
- Creatinine
- Estimated glomerular filtration rate
- Potassium
- Sodium
- ALT
- AST
- Hemoglobin
- White blood cell count
- Platelet count

Future:

- Urinalysis
- Iron studies
- Vitamin levels
- Coagulation studies
- Microbiology
- Pathology
- Imaging reports
- Specialty-specific biomarkers

## 6.1.3 Required Capabilities

The system shall:

- Ingest laboratory and diagnostic results.
- Normalize local test codes to canonical markers.
- Normalize units.
- Validate specimen type.
- interpret client-provided reference ranges.
- Compare current values against historical values.
- Determine clinical significance.
- Identify routine, abnormal, high-priority, and critical results.
- Retrieve relevant patient context.
- Select an applicable protocol.
- Apply health system and clinician customization.
- Generate a clinician summary.
- Generate patient-friendly communication.
- Route the item to the correct inbox or pool.
- Support human approval.
- Support automatic handling only for explicitly approved low-risk scenarios.
- Record clinician actions.
- Track patient follow-up.
- Produce a complete decision trace.

## 6.1.4 Result Classification

Every result workflow must produce:

- Normal
- Expected abnormal
- Clinically insignificant abnormal
- Routine follow-up required
- Clinician review required
- High-priority review required
- Critical escalation required
- Unsupported
- Insufficient data
- Conflicting data

## 6.1.5 Result Output

```json
{
  "classification": "routine_follow_up",
  "priority": "normal",
  "recommended_action": "repeat_test",
  "recommended_interval_days": 90,
  "automation_status": "requires_clinician_approval",
  "patient_message_template": "a1c_above_target_v4",
  "reason_codes": [
    "A1C_ABOVE_CONFIGURED_TARGET",
    "A1C_RISING_TREND"
  ],
  "clinical_facts_used": [
    "current_a1c",
    "prior_a1c",
    "diabetes_diagnosis",
    "active_diabetes_medications"
  ]
}
```

## 6.1.6 Safety Requirements

- Critical values must bypass normal queues.
- Critical thresholds must not be weakened by client or clinician overrides.
- Missing required clinical context must suppress automation.
- Conflicting results must require manual review.
- Pediatric, pregnancy, transplant, oncology, and other protected cohorts must support separate constraints.
- Unsupported units must block clinical interpretation.
- Patient messages must not imply a diagnosis that has not been confirmed.
- Patient messages must clearly distinguish education from clinician-confirmed treatment plans.

---

# 6.2 Patient Message Intelligence

## 6.2.1 Objective

Classify, summarize, prioritize, route, and assist with responses to incoming patient messages.

## 6.2.2 Message Categories

- New symptom
- Existing symptom worsening
- Medication question
- Side effect
- Refill request
- Laboratory result question
- Imaging result question
- Appointment request
- Referral request
- Form request
- Billing or administrative question
- Post-procedure concern
- Chronic disease follow-up
- Behavioral health concern
- Pregnancy-related concern
- Potential emergency
- General question
- Unknown

## 6.2.3 Required Capabilities

The system shall:

- Ingest patient messages from supported EHR channels.
- Detect language.
- Extract symptoms, medications, duration, severity, and requested action.
- Classify message category.
- Assign urgency.
- Detect red flags.
- Retrieve relevant chart context.
- Generate a structured summary.
- Ask approved follow-up questions when information is missing.
- Route to the appropriate clinician, nurse, pool, or administrative team.
- Suggest a response.
- Automate only approved non-clinical or low-risk responses.
- Escalate emergencies immediately.
- Preserve the original patient message.
- Record all model output and validation results.
- Support multilingual communication.

## 6.2.4 Urgency Levels

- Emergency
- Immediate clinician review
- Same-day review
- Review within 24 hours
- Routine clinical
- Administrative
- Informational

## 6.2.5 Structured Message Output

```json
{
  "category": "medication_side_effect",
  "urgency": "same_day_review",
  "medication": "lisinopril",
  "symptoms": ["persistent dry cough"],
  "duration": "14 days",
  "red_flags": [],
  "missing_information": [],
  "suggested_route": "primary_care_clinician",
  "summary": "Patient reports a persistent dry cough beginning after starting lisinopril."
}
```

## 6.2.6 Safety Requirements

- Emergency symptom detection must use deterministic rules in addition to model classification.
- The system must not falsely reassure patients when emergency red flags are present.
- High-risk categories must never be fully auto-resolved.
- Model confidence alone must not determine clinical urgency.
- Patient identity and encounter context must be validated before chart-based reasoning.
- The system must detect and prevent cross-patient context contamination.

---

# 6.3 Prescription and Refill Intelligence

## 6.3.1 Objective

Reduce the chart review and routing effort required for prescription refill requests while maintaining patient safety.

## 6.3.2 Required Capabilities

The system shall evaluate:

- Medication identity
- Requested dose
- Active prescription status
- Prescribing clinician
- Refill timing
- Medication class
- Controlled substance status
- Relevant diagnosis
- Last visit date
- Required monitoring labs
- Recent vital signs
- Allergies
- Contraindications
- Drug interactions
- Pregnancy status
- Renal function
- Hepatic function
- Adverse events
- Medication discontinuation
- Client policy
- Clinician preference

## 6.3.3 Possible Outcomes

- Auto-approve
- Prepare for one-click approval
- Route to nurse
- Route to prescribing clinician
- Request laboratory testing
- Request appointment
- Reject as too early
- Reject because medication was discontinued
- Escalate for contraindication
- Escalate for missing required data
- Escalate for controlled-substance policy
- Unsupported medication workflow

## 6.3.4 Refill Decision Output

```json
{
  "decision": "requires_clinician_review",
  "reason_codes": [
    "MONITORING_LAB_OVERDUE"
  ],
  "required_actions": [
    "ORDER_RENAL_FUNCTION_PANEL"
  ],
  "context": {
    "last_visit_days": 210,
    "last_creatinine_days": 430,
    "active_medication": true,
    "requested_dose_matches": true
  }
}
```

## 6.3.5 Safety Requirements

- Controlled substances must require separate policy.
- Medication changes must never be generated solely by an LLM.
- Allergies and contraindications must be evaluated deterministically.
- Required monitoring must be client-configurable.
- Missing medication identity must block automation.
- Dose mismatch must require manual review.
- The system must log the exact data used for every refill recommendation.

---

# 6.4 Clinical Context Engine

## 6.4.1 Objective

Resolve the effective clinical logic for a workflow using global, organizational, specialty, cohort, clinician, and patient context.

## 6.4.2 Context Hierarchy

1. Global safety constraints
2. Global clinical protocol
3. Specialty overlay
4. Health system overlay
5. Site overlay
6. Department overlay
7. Practice overlay
8. Patient cohort overlay
9. Clinician preference overlay
10. Patient-specific facts
11. Workflow-specific metadata

## 6.4.3 Precedence Rules

- Global safety constraints cannot be disabled.
- Client configuration may make rules more conservative.
- Clinician preferences may affect wording, follow-up cadence, and permitted low-risk workflow behavior.
- Clinician preferences may not weaken global or client safety constraints.
- Cohort constraints override routine clinician preferences.
- Patient-specific contraindications override general preferences.
- Conflicting configurations must suppress automation.
- Every effective configuration must be reproducible from versioned inputs.

## 6.4.4 Context Resolution Output

```json
{
  "effective_protocol_id": "a1c_management",
  "effective_protocol_version": 18,
  "applied_overlays": [
    "endocrinology_v5",
    "tenant_123_v8",
    "clinician_456_v3"
  ],
  "blocked_overlays": [],
  "safety_constraints": [
    "pregnancy_manual_review",
    "critical_glucose_escalation"
  ]
}
```

---

# 6.5 Protocol and Rule Management

## 6.5.1 Objective

Allow clinical experts to author, test, approve, deploy, and retire clinical logic without application code changes.

## 6.5.2 Rule Components

Each rule must include:

- Rule identifier
- Human-readable name
- Description
- Scope
- Version
- Status
- Effective date
- Expiration date
- Author
- Clinical approver
- Engineering approver where required
- Evidence source
- Input facts
- Conditions
- Exclusions
- Actions
- Routing behavior
- Communication template
- Safety requirements
- Automation eligibility
- Test cases
- Change reason
- Audit metadata

## 6.5.3 Example Rule

```yaml
id: a1c_above_target
version: 12
scope:
  specialties:
    - primary_care
    - endocrinology

when:
  all:
    - fact: patient.has_diabetes
      operator: equals
      value: true
    - fact: lab.a1c
      operator: greater_than_or_equal
      value: 7.0
    - fact: lab.a1c
      operator: less_than
      value: 9.0

then:
  classification: routine_clinician_review
  recommended_action: evaluate_current_plan
  patient_template: diabetes_a1c_above_target
  clinician_context:
    - prior_a1c
    - diabetes_medications
    - renal_function
    - last_diabetes_visit

safety:
  requires_manual_review: true
  excluded_when:
    - pregnancy
    - pediatric_patient
```

## 6.5.4 Rule States

- Draft
- In review
- Approved
- Scheduled
- Active
- Deprecated
- Retired
- Rolled back

## 6.5.5 Rule Authoring Requirements

- Visual rule builder
- Structured condition editor
- Nested Boolean logic
- Type-safe operators
- Data dictionary
- Reusable predicates
- Reusable action groups
- Evidence references
- Template association
- Scope selector
- Version comparison
- Inline validation
- Conflict warnings
- Test execution
- Approval routing

## 6.5.6 Rule Simulation

Users must be able to:

- Create a synthetic patient scenario.
- Load a de-identified historical case.
- Select a tenant and clinician context.
- Run a proposed rule version.
- Compare current and proposed behavior.
- Inspect matched and rejected rules.
- Review all facts used.
- Review missing facts.
- Preview patient communication.
- Preview clinician summary.
- Export simulation results.

## 6.5.7 Impact Analysis

Before activation, the system must report:

- Number of tenants affected
- Number of specialties affected
- Number of clinicians affected
- Historical case behavior changes
- Conflicting rules
- Overridden customizations
- Missing data dependencies
- Automation rate change
- Escalation rate change
- High-risk cohort impact

## 6.5.8 Deployment Requirements

- Scheduled release
- Percentage-based rollout
- Tenant-based rollout
- Site-based rollout
- Specialty-based rollout
- Clinician cohort rollout
- Shadow mode
- Automatic rollback conditions
- Manual rollback
- Deployment audit

---

# 6.6 Clinical Programming Workbench

## 6.6.1 Objective

Provide internal clinical operations teams with tools to scale protocol creation, mapping, QA, and customer onboarding.

## 6.6.2 Required Features

- Protocol catalog
- Rule editor
- Mapping workbench
- Unknown-code queue
- Failed-case queue
- No-match case queue
- Multiple-match case queue
- Override review
- Edit-difference analysis
- Feedback dashboard
- Test-case management
- Release management
- Customer configuration browser
- Data lineage viewer
- Message replay
- Synthetic event generation
- Clinical gap detection

## 6.6.3 Gap Detection

The platform must identify:

- No protocol matched
- Multiple incompatible protocols matched
- Required data missing
- Unknown laboratory marker
- Unknown medication
- Unsupported unit
- Missing tenant mapping
- Unexpected clinician override pattern
- Increased patient follow-up
- Increased edit rate
- Increased safety suppression
- New EHR payload structure

---

# 6.7 Healthcare Integration Platform

## 6.7.1 Supported Integration Methods

- HL7 v2 over MLLP
- FHIR R4 REST APIs
- SMART on FHIR
- Backend service authorization
- Vendor REST APIs
- Webhooks
- Secure file transfer
- Batch import
- EHR-specific application frameworks
- Patient portal messaging APIs
- Task and inbox write-back APIs

## 6.7.2 HL7 Message Types

Initial:

- ADT
- ORU
- ORM
- MDM

Future:

- SIU
- RDE
- pharmacy-specific interfaces
- custom Z-segments

## 6.7.3 FHIR Resources

Initial:

- Patient
- Practitioner
- PractitionerRole
- Organization
- Encounter
- Observation
- DiagnosticReport
- Condition
- MedicationRequest
- MedicationStatement
- AllergyIntolerance
- ServiceRequest
- Communication
- Task
- DocumentReference

## 6.7.4 Integration Gateway Requirements

The gateway shall:

- Authenticate inbound connections.
- Resolve tenant.
- Validate payload.
- Store raw payload.
- Generate idempotency key.
- Detect duplicates.
- Normalize timestamps.
- Publish canonical events.
- Acknowledge or reject messages.
- Record latency.
- Route failures to a dead-letter queue.
- Support replay.
- Protect against malformed payloads.
- Rate limit abusive sources.
- Support tenant-specific mappings.
- Support message-level auditability.

## 6.7.5 Integration Monitoring

Per interface:

- Connection status
- Last successful message
- Last failed message
- Throughput
- Error rate
- Queue depth
- Processing latency
- Duplicate count
- Unknown-code count
- Patient match failure count
- Missing required field count
- Write-back failure count
- Retry count
- Dead-letter count

## 6.7.6 Idempotency

Every inbound event must have a stable idempotency key based on:

- Tenant
- Source system
- Message identifier
- Patient identifier
- Event type
- Result or request identifier
- Event timestamp where needed

Duplicate events must not create duplicate patient communication or duplicate clinical tasks.

---

# 6.8 Clinical Terminology and Mapping

## 6.8.1 Required Terminologies

- LOINC
- RxNorm
- ICD-10-CM
- SNOMED CT where licensed and appropriate
- UCUM
- Local EHR codes
- Local laboratory codes
- Local medication identifiers

## 6.8.2 Marker Mapping Requirements

- Exact code mapping
- Canonical code mapping
- Name similarity
- Unit compatibility
- Specimen compatibility
- Reference range handling
- Client-specific aliases
- Mapping confidence
- Human approval
- Version history
- Effective date
- Rollback
- Impact analysis

## 6.8.3 Mapping Proposal

```json
{
  "source_code": "LAB-88291",
  "source_name": "HbA1c",
  "canonical_marker": "hemoglobin_a1c",
  "loinc": "4548-4",
  "source_unit": "%",
  "canonical_unit": "%",
  "confidence": 0.98,
  "status": "pending_review"
}
```

## 6.8.4 Safety Rules

- Unsupported units must block interpretation.
- Unapproved mappings must not be used in production.
- Mapping changes must trigger regression tests.
- High-impact mapping changes must require clinical review.
- Unit conversion must be deterministic and tested.
- Specimen mismatches must require review.

---

# 6.9 Communication Generation

## 6.9.1 Objective

Generate patient and clinician communication from structured clinical decisions while preserving accuracy, approved language, and personalization.

## 6.9.2 Communication Types

- Patient result explanation
- Patient follow-up instruction
- Refill response
- Appointment request
- Missing-information request
- Clinician summary
- Nurse triage summary
- Escalation notice
- Administrative response

## 6.9.3 Generation Inputs

- Structured clinical facts
- Deterministic decision
- Approved template
- Health system language
- Clinician tone preferences
- Patient language preference
- Patient reading level
- Required safety warnings
- Prohibited claims

## 6.9.4 LLM Constraints

The model may:

- Summarize
- Classify
- Extract structured fields
- Rewrite tone
- Simplify language
- Translate approved content

The model may not:

- Choose critical thresholds
- Override contraindications
- Diagnose autonomously
- Prescribe treatment
- Weaken required warnings
- Invent patient facts
- Invent follow-up plans
- Modify mandatory clinical actions

## 6.9.5 Validation

Every generated message must pass:

- Schema validation
- Fact consistency
- Medication consistency
- Numeric consistency
- Required warning validation
- Prohibited-claim validation
- Tenant policy validation
- Language validation
- PHI boundary validation
- Template compliance
- Hallucination checks

## 6.9.6 Deterministic Fallback

If generation fails:

- Use an approved fixed template.
- Route to human review if required.
- Do not drop the workflow.
- Record the failure.
- Preserve the deterministic clinical decision.

---

# 6.10 Clinician Experience

## 6.10.1 Requirements

The clinician view must show:

- Priority
- Workflow type
- Patient identity
- Concise summary
- Relevant chart facts
- Clinical trend
- Recommended action
- Patient communication preview
- Reason codes
- Automation status
- Approve control
- Edit control
- Override control
- Escalate control
- Close control
- View reasoning control
- View source chart control

## 6.10.2 Design Principles

- Do not require a separate workflow when EHR embedding is possible.
- Show only relevant clinical context.
- Make critical information visually distinct.
- Avoid alert fatigue.
- Require minimal clicks.
- Preserve clinician control.
- Make the reason for a recommendation immediately available.
- Never hide data uncertainty.

---

# 6.11 Patient Experience

## 6.11.1 Requirements

Patient communication must:

- Use plain language.
- State what was tested.
- Explain whether the result is normal, abnormal, or awaiting review.
- Avoid unsupported reassurance.
- Explain next steps.
- State when the clinician will review.
- State when urgent care is needed.
- Use the patient’s preferred language where supported.
- Meet accessibility requirements.
- Be delivered through approved channels.
- Preserve health system branding.

## 6.11.2 Reading Level

Default target:

- Sixth to eighth grade reading level

Configurable by:

- Health system
- Patient population
- Language
- Workflow

---

# 6.12 Analytics

## 6.12.1 Executive Dashboard

- Inbox volume
- Inbox growth
- Time burden
- Automation rate
- After-hours work
- Patient response time
- Workflow savings
- Adoption
- Safety metrics
- Tenant comparison

## 6.12.2 Clinical Dashboard

- Agreement rate
- Edit rate
- Override rate
- Escalation rate
- Workflow outcomes
- Protocol performance
- Specialty performance
- Cohort performance

## 6.12.3 Operations Dashboard

- Integration health
- Queue health
- Processing latency
- Data quality
- Unknown mappings
- Failed workflows
- Write-back status
- Release health

## 6.12.4 Analytics Dimensions

- Tenant
- Site
- Department
- Specialty
- Clinician
- Workflow
- Protocol
- Patient cohort
- Time period
- Integration source
- Automation mode

## 6.12.5 Privacy Requirements

- Minimum necessary reporting
- Aggregation thresholds
- Role-based access
- Export controls
- Audit logging
- De-identification for cross-tenant analysis

---

# 7. Architecture

# 7.1 High-Level Architecture

```text
EHRs, Labs, Portals, and Health Systems
              |
              v
       Integration Gateway
              |
              v
        Durable Event Bus
              |
     +--------+--------+
     |        |        |
     v        v        v
 Results   Messages   Rx Workers
     |        |        |
     +--------+--------+
              |
              v
   Canonical Clinical Data Layer
              |
              v
     Clinical Context Builder
              |
              v
 Configuration Resolution Service
              |
              v
      Clinical Protocol Engine
              |
      +-------+-------+
      |               |
      v               v
Deterministic      LLM Assistance
Templates          and Generation
      |               |
      +-------+-------+
              |
              v
   Output Validation and Safety
              |
              v
 EHR Delivery, Patient Messaging,
 Tasks, Routing, and Clinician UI
              |
              v
 Feedback, Analytics, and Learning
```

# 7.2 Recommended Technology Stack

## Backend

- Python
- Django
- Django REST Framework
- Pydantic
- PostgreSQL
- Redis
- Celery with SQS or Temporal
- boto3
- FHIR client libraries
- HL7 parser
- OpenTelemetry

## Frontend

- TypeScript
- Next.js
- React
- Server-side rendering for administration
- Component library with accessibility support
- Role-based navigation

## Infrastructure

- AWS
- Docker
- Terraform
- GitHub Actions
- ECS or EKS
- RDS PostgreSQL
- ElastiCache Redis
- S3
- SQS
- EventBridge
- AWS Secrets Manager
- KMS
- CloudTrail
- WAF
- PrivateLink where supported

## Observability

- Datadog
- Sentry
- OpenTelemetry
- CloudWatch
- Structured application logs
- Clinical workflow metrics

---

# 7.3 Service Boundaries

Recommended logical services:

1. Identity and tenant service
2. Integration gateway
3. HL7 adapter
4. FHIR adapter
5. Canonical data service
6. Patient matching service
7. Terminology service
8. Context builder
9. Configuration service
10. Protocol engine
11. Workflow orchestration service
12. Communication generation service
13. Output validation service
14. Delivery service
15. Feedback service
16. Analytics service
17. Clinical programming workbench
18. Audit service
19. Notification and alert service

Initial implementation may use a modular monolith with explicit boundaries. Services should be separated only when scaling, isolation, ownership, or reliability requirements justify it.

---

# 7.4 Modular Monolith Strategy

Initial backend structure:

```text
apps/
  identity/
  tenants/
  integrations/
  terminology/
  clinical_data/
  context/
  protocols/
  workflows/
  generation/
  safety/
  delivery/
  feedback/
  analytics/
  audit/
  operations/
```

Requirements:

- Each module owns its domain models.
- Cross-module access must use service interfaces.
- Domain events must be explicit.
- Clinical decision logic must not be embedded in controllers.
- Integration-specific logic must not leak into protocol logic.
- Tenant customization must not use code branches.

---

# 7.5 Event-Driven Architecture

## Core Events

- PatientUpdated
- EncounterUpdated
- ObservationReceived
- DiagnosticReportReceived
- PatientMessageReceived
- RefillRequestReceived
- ContextBuilt
- ProtocolEvaluated
- DecisionCreated
- CommunicationGenerated
- CommunicationValidated
- WorkflowEscalated
- DeliverySucceeded
- DeliveryFailed
- ClinicianApproved
- ClinicianEdited
- ClinicianOverrode
- PatientResponded
- ProtocolDeployed
- MappingChanged

## Event Requirements

- Immutable
- Versioned schema
- Tenant-aware
- Correlation identifier
- Causation identifier
- Idempotency identifier
- Timestamp
- Source
- Audit metadata
- Retry policy
- Dead-letter policy

---

# 7.6 Workflow Orchestration

A workflow engine must support:

- Long-running processes
- Durable retries
- Timeouts
- Human review pauses
- Scheduled follow-up
- Compensation
- Idempotency
- Reprocessing
- Auditability
- Versioned workflows

Recommended:

- Temporal for complex durable workflows
- SQS and workers for simpler event processing
- Step Functions for AWS-native orchestration where appropriate

---

# 8. Data Architecture

# 8.1 Core Data Domains

## Tenancy

- Organization
- Site
- Department
- Practice
- Specialty
- CareTeam
- Practitioner
- PractitionerRole
- User
- Role
- Permission
- PractitionerPreference

## Integration

- Integration
- IntegrationEndpoint
- IntegrationCredential
- IntegrationMapping
- InboundMessage
- OutboundMessage
- DeliveryAttempt
- DeadLetterEvent

## Clinical Data

- PatientReference
- Encounter
- Condition
- Observation
- DiagnosticReport
- Medication
- MedicationRequest
- Allergy
- Procedure
- ClinicalDocument
- Communication
- Task

## Clinical Logic

- Protocol
- ProtocolVersion
- Rule
- RuleCondition
- RuleAction
- RuleEvidence
- ProtocolScope
- ProtocolOverride
- SafetyConstraint
- CommunicationTemplate

## Workflow

- WorkflowInstance
- ContextSnapshot
- ProtocolEvaluation
- ClinicalDecision
- GeneratedCommunication
- HumanReview
- Escalation
- WorkflowAction
- Outcome

## Feedback

- ClinicianApproval
- ClinicianEdit
- ClinicianOverride
- PatientResponse
- ProtocolFeedback
- ConfigurationRecommendation

## Operations

- MappingProposal
- MappingReview
- IntegrationError
- Alert
- Incident
- AuditEvent
- Deployment
- Rollback

---

# 8.2 Canonical Clinical Model

The platform must not rely directly on vendor-specific EHR structures.

Every incoming message must be transformed into a canonical model that supports:

- Stable protocol inputs
- Cross-EHR workflows
- Consistent terminology
- Historical trend calculations
- Reprocessing
- Auditability

Example:

```json
{
  "tenant_id": "tenant_123",
  "patient_id": "internal_patient_789",
  "event_type": "lab_result",
  "source": {
    "system": "ehr_vendor",
    "message_id": "source-message-123"
  },
  "test": {
    "code_system": "LOINC",
    "code": "4548-4",
    "canonical_name": "hemoglobin_a1c",
    "value": 7.4,
    "unit": "%",
    "reference_range": {
      "low": 4.0,
      "high": 5.6
    }
  },
  "observed_at": "2026-07-14T15:42:00Z"
}
```

---

# 8.3 Context Snapshot

Every protocol evaluation must use an immutable context snapshot.

```json
{
  "patient_age": 54,
  "has_diabetes": true,
  "current_a1c": 7.4,
  "prior_a1c": 6.9,
  "a1c_trend": "rising",
  "active_diabetes_medications": ["metformin"],
  "recent_medication_change": false,
  "renal_impairment": false,
  "pregnancy": false,
  "context_created_at": "2026-07-14T15:43:12Z"
}
```

The snapshot must record:

- Source record identifiers
- Source timestamps
- Data freshness
- Missing facts
- Conflicting facts
- Transformations
- Terminology mappings
- Context builder version

---

# 8.4 Data Retention

Configurable by tenant and contract.

Data classes:

- Raw inbound messages
- Canonical clinical events
- Context snapshots
- Decisions
- Communications
- Audit logs
- Analytics aggregates
- Model prompts and outputs
- Integration logs

Requirements:

- Tenant-specific retention
- Legal hold support
- Automated purge
- Purge verification
- Backup expiration
- Data export
- Contract termination workflow

---

# 9. API Requirements

# 9.1 API Principles

- REST or GraphQL for administration
- FHIR-compatible APIs where appropriate
- OpenAPI documentation
- Versioned endpoints
- Tenant isolation
- OAuth 2.0
- Fine-grained authorization
- Idempotency keys
- Correlation identifiers
- Structured errors
- Rate limiting
- Audit logging

# 9.2 Example Endpoints

## Protocols

```text
POST   /api/v1/protocols
GET    /api/v1/protocols
GET    /api/v1/protocols/{id}
POST   /api/v1/protocols/{id}/versions
POST   /api/v1/protocols/{id}/simulate
POST   /api/v1/protocols/{id}/approve
POST   /api/v1/protocols/{id}/deploy
POST   /api/v1/protocols/{id}/rollback
```

## Workflows

```text
GET    /api/v1/workflows
GET    /api/v1/workflows/{id}
POST   /api/v1/workflows/{id}/approve
POST   /api/v1/workflows/{id}/edit
POST   /api/v1/workflows/{id}/override
POST   /api/v1/workflows/{id}/escalate
POST   /api/v1/workflows/{id}/replay
```

## Integrations

```text
POST   /api/v1/integrations
GET    /api/v1/integrations
GET    /api/v1/integrations/{id}/health
GET    /api/v1/integrations/{id}/errors
POST   /api/v1/integrations/{id}/test
POST   /api/v1/integrations/{id}/replay
```

## Mappings

```text
GET    /api/v1/mappings
POST   /api/v1/mappings/proposals
POST   /api/v1/mappings/{id}/approve
POST   /api/v1/mappings/{id}/reject
GET    /api/v1/mappings/unknown
```

---

# 10. Security and Compliance

# 10.1 Compliance Targets

- HIPAA
- SOC 2 Type II
- HITECH
- Applicable state privacy laws
- Customer security requirements
- Business Associate Agreements

# 10.2 Identity and Access

- Single sign-on
- SAML
- OpenID Connect
- Role-based access control
- Attribute-based controls where required
- Least privilege
- Multi-factor authentication
- Session controls
- Device controls where supported
- Break-glass access
- Just-in-time privileged access
- Access review

## Roles

- Platform administrator
- Tenant administrator
- Clinical programmer
- Clinical reviewer
- Integration engineer
- Support engineer
- Security reviewer
- Read-only auditor
- Clinician
- Nurse
- Operations analyst

# 10.3 Data Security

- TLS for all network traffic
- Encryption at rest
- KMS-managed keys
- Tenant-aware encryption where required
- Secrets management
- Private subnets
- Restricted egress
- WAF
- DDoS protection
- Database activity monitoring
- Backup encryption
- Secure deletion
- PHI-safe logs

# 10.4 Audit Requirements

Audit:

- Authentication
- PHI access
- Rule creation
- Rule modification
- Rule approval
- Rule deployment
- Configuration change
- Mapping change
- Workflow decision
- LLM usage
- Message delivery
- Clinician action
- Administrative export
- Support access
- Data purge

Every audit record must include:

- Actor
- Action
- Resource
- Tenant
- Timestamp
- Source IP
- Session
- Before state
- After state
- Reason
- Correlation identifier

# 10.5 LLM Security

- Approved model providers only
- BAA where PHI is processed
- No training on customer data
- Retention disabled or contractually controlled
- Prompt injection defenses
- PHI-safe logging
- Model allowlist
- Model version pinning
- Output validation
- Cost controls
- Data minimization
- Provider failover
- Emergency kill switch

---

# 11. Safety Architecture

# 11.1 Safety Layers

1. Input validation
2. Patient identity validation
3. Terminology validation
4. Context completeness validation
5. Deterministic clinical rules
6. Configuration conflict detection
7. Automation eligibility rules
8. LLM output validation
9. Communication policy validation
10. Human review
11. Delivery confirmation
12. Post-deployment monitoring

# 11.2 Automation Modes

- Disabled
- Shadow
- Suggestion only
- Human approval required
- One-click approval
- Limited auto-action
- Full auto-action for explicitly approved low-risk cases

# 11.3 Automation Eligibility

Eligibility must consider:

- Workflow
- Protocol
- Tenant
- Specialty
- Clinician
- Patient cohort
- Data completeness
- Safety constraints
- Historical agreement rate
- Current model status
- Integration health
- Incident state

# 11.4 Kill Switches

- Global
- Tenant
- Site
- Specialty
- Workflow
- Protocol
- Clinician
- Model provider
- Integration
- Communication channel

---

# 12. Observability

# 12.1 Technical Metrics

- Request latency
- Error rate
- CPU
- Memory
- Database connections
- Cache hit rate
- Queue depth
- Worker health
- Event processing latency
- Retry rate
- Dead-letter rate
- API availability

# 12.2 Clinical Workflow Metrics

- No-match rate
- Multiple-match rate
- Missing-context rate
- Unknown-marker rate
- Unit mismatch rate
- Automation suppression rate
- Clinician agreement rate
- Clinician edit rate
- Clinician override rate
- Critical escalation latency
- Patient message delivery failure
- EHR write-back failure

# 12.3 Alerts

Critical alerts:

- Interface disconnected
- Critical event delayed
- Silent event gap
- Write-back failure spike
- Unknown mapping spike
- Rule conflict
- Patient identity mismatch
- Cross-tenant access attempt
- LLM validation failure spike
- Critical workflow automation anomaly

# 12.4 Service-Level Objectives

- 99.9 percent ingestion availability
- 99 percent of routine events processed within two minutes
- 99 percent of critical events processed within 30 seconds
- Zero silent message loss
- 99.9 percent successful audit recording
- 99 percent successful approved-channel delivery
- 100 percent decision trace availability for completed workflows

---

# 13. Testing Strategy

# 13.1 Test Types

- Unit tests
- Domain tests
- Rule tests
- Integration tests
- Contract tests
- EHR simulator tests
- End-to-end tests
- Security tests
- Performance tests
- Chaos tests
- Clinical regression tests
- LLM evaluation tests
- Accessibility tests
- Disaster recovery tests

# 13.2 Clinical Test Cases

Every protocol version must include:

- Positive cases
- Negative cases
- Boundary values
- Missing data
- Conflicting data
- High-risk cohorts
- Unit variants
- Client overrides
- Clinician overrides
- Historical behavior comparison

# 13.3 Golden Dataset

Maintain a governed dataset containing:

- De-identified historical cases
- Synthetic edge cases
- Expected classifications
- Expected actions
- Expected communication constraints
- Expected safety behavior

# 13.4 LLM Evaluations

Evaluate:

- Factual consistency
- Unsupported claims
- Numeric accuracy
- Medication accuracy
- Omission of warnings
- Tone
- Reading level
- Classification accuracy
- Extraction accuracy
- Translation consistency
- Prompt injection resistance

# 13.5 Release Gates

A release cannot proceed if:

- Critical regression tests fail.
- Safety rules fail.
- Mapping validation fails.
- Cross-tenant isolation tests fail.
- Required clinical approval is missing.
- Historical high-risk cases change unexpectedly.
- Observability is incomplete.
- Rollback is unavailable.

---

# 14. Deployment and Release Management

# 14.1 Environments

- Local
- Development
- Integration
- Clinical QA
- Staging
- Customer sandbox
- Production

# 14.2 Deployment Strategy

- Infrastructure as code
- Immutable containers
- Signed artifacts
- Automated vulnerability scanning
- Database migration validation
- Blue-green or canary deployment
- Feature flags
- Tenant-level enablement
- Rollback automation
- Release audit

# 14.3 Clinical Configuration Release

Clinical configuration must be deployed separately from application code.

Required:

- Versioned bundle
- Approval record
- Impact report
- Test results
- Effective date
- Target scope
- Rollout plan
- Rollback version
- Monitoring plan

---

# 15. Disaster Recovery and Business Continuity

Requirements:

- Multi-availability-zone deployment
- Automated database backups
- Point-in-time recovery
- S3 versioning
- Cross-region backup where contractually required
- Documented recovery procedures
- Quarterly restore tests
- Integration replay capability
- Workflow reconciliation
- Manual operations fallback

Targets:

- Recovery time objective: four hours for core services
- Recovery point objective: 15 minutes for transactional data
- Lower targets may be required for critical customer workflows

---

# 16. Implementation Phases

# Phase 0: Foundation

Deliver:

- Product domain model
- Tenant model
- Identity and RBAC
- Audit framework
- Infrastructure baseline
- CI/CD
- Observability baseline
- Security controls
- Canonical event schema

Exit criteria:

- Tenant-isolated platform operational
- Audit records generated
- Infrastructure reproducible
- Production logging PHI-safe

# Phase 1: Results Intelligence MVP

Deliver:

- FHIR integration
- Core laboratory markers
- Marker mapping
- Unit normalization
- Context builder
- Deterministic rule engine
- Clinician summary
- Patient message draft
- Human approval
- Decision trace

Exit criteria:

- End-to-end result workflow works in sandbox
- At least five markers supported
- All decisions explainable
- No automated patient delivery without approval

# Phase 2: Clinical Rule Studio

Deliver:

- Rule authoring
- Simulation
- Test cases
- Versioning
- Approval
- Deployment
- Rollback
- Conflict detection

Exit criteria:

- Clinical programmer can create and deploy an approved rule without code change
- Impact analysis available
- Regression testing enforced

# Phase 3: Production EHR Integration

Deliver:

- HL7 ingestion
- FHIR production connection
- EHR write-back
- Patient portal messaging
- Queue and retry infrastructure
- Integration health dashboard
- Dead-letter tooling
- Message replay

Exit criteria:

- Production-grade interface monitoring
- Zero silent failures
- Reprocessing tested
- Tenant-specific mappings supported

# Phase 4: Prescription Intelligence

Deliver:

- Refill request ingestion
- Medication normalization
- Refill protocol engine
- Monitoring checks
- Contraindication checks
- Routing
- Human approval

Exit criteria:

- Approved medication classes supported
- All refill decisions traceable
- Safety exclusions enforced

# Phase 5: Patient Message Intelligence

Deliver:

- Message classification
- Red-flag detection
- Structured extraction
- Summary
- Routing
- Follow-up questions
- Draft response

Exit criteria:

- Emergency messages escalated
- Classification performance meets clinical threshold
- No high-risk autonomous resolution

# Phase 6: Analytics and Personalization

Deliver:

- Clinical agreement analytics
- Workflow performance
- Edit analysis
- Clinician preference profile
- Configuration recommendations
- Controlled personalization

Exit criteria:

- Personalization remains auditable
- Recommendations require approval
- Cross-tenant privacy controls validated

---

# 17. Initial Team Requirements

## Engineering

- Principal architect
- Backend engineers
- Frontend engineer
- Integration engineer
- Platform engineer
- Data engineer
- ML or applied AI engineer
- Security engineer
- QA and test automation engineer

## Clinical

- Medical director
- Clinical informaticist
- Clinical programmers
- Specialty reviewers
- Nursing workflow expert
- Medication safety reviewer

## Product and Operations

- Product manager
- Implementation manager
- Customer success
- Clinical operations lead
- Compliance lead
- Security and privacy lead

---

# 18. Key Risks and Mitigations

## Risk: Incorrect clinical rule

Mitigation:

- Clinical approval
- Versioning
- Regression tests
- Shadow mode
- Progressive rollout
- Rollback
- Monitoring

## Risk: EHR data is missing or incorrect

Mitigation:

- Context completeness checks
- Data freshness indicators
- Integration alerts
- Manual review
- Tenant-specific mapping

## Risk: LLM hallucination

Mitigation:

- Deterministic decision layer
- Structured generation
- Approved templates
- Validation
- Human review
- Fixed fallback

## Risk: Configuration conflict

Mitigation:

- Explicit precedence
- Conflict detector
- Impact analysis
- Protected safety constraints

## Risk: Cross-tenant data exposure

Mitigation:

- Tenant-aware data model
- Row-level isolation
- Authorization testing
- Separate encryption controls where needed
- Audit alerts

## Risk: Clinician distrust

Mitigation:

- Explainable reasoning
- Shadow mode
- Easy override
- Personalization
- Feedback loop
- Transparent safety behavior

## Risk: Alert fatigue

Mitigation:

- Prioritization
- Tiered alerts
- Low-noise workflows
- Specialty-specific thresholds
- Continuous monitoring

## Risk: Integration fragility

Mitigation:

- Canonical model
- Adapter architecture
- Dead-letter queues
- Replay
- Monitoring
- Contract tests

---

# 19. MVP Acceptance Criteria

The MVP is complete when:

1. A laboratory result can be received through FHIR.
2. The result is normalized to a canonical marker.
3. Relevant patient context is retrieved.
4. A versioned deterministic protocol is evaluated.
5. The output includes classification, priority, recommended action, and reason codes.
6. A patient-friendly message is generated from approved inputs.
7. The message passes validation.
8. A clinician can approve, edit, or reject the message.
9. Every action is audited.
10. The workflow can be replayed.
11. Failed events appear in an operations queue.
12. Tenant isolation is validated.
13. Critical values cannot be auto-resolved.
14. Rule changes can be tested before deployment.
15. A deployed rule can be rolled back.
16. Operational metrics are visible.
17. No inbound event can disappear silently.

---

# 20. Recommended Initial Repository Structure

```text
clinara-healthos/
  apps/
    api/
    web/
    workers/
  packages/
    clinical-models/
    protocol-engine/
    integration-sdk/
    terminology/
    shared-types/
    ui/
  infrastructure/
    terraform/
    docker/
    monitoring/
  services/
    integration-gateway/
    workflow-orchestrator/
    communication-service/
  docs/
    architecture/
    protocols/
    security/
    integrations/
    operations/
  tests/
    unit/
    integration/
    clinical-regression/
    end-to-end/
    performance/
```

---

# 21. Final Architecture Decision

Clinara HealthOS should be designed as a governed clinical workflow platform, not as a general-purpose chatbot.

The platform’s most valuable assets will be:

- Its clinical protocol model
- Its configuration hierarchy
- Its EHR integration layer
- Its patient-context model
- Its safety architecture
- Its clinical feedback dataset
- Its operational tooling
- Its ability to personalize workflows without creating unmaintainable client-specific code

The first production milestone should prioritize correctness, auditability, integration reliability, and clinician trust over automation volume.

A low-risk workflow with 98 percent clinical agreement is more valuable than a broad workflow with unpredictable behavior.

