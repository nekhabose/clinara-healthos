# Authoring a specialty protocol pack (Phase 10 — Specialty Protocol Breadth)

This playbook lets a clinical programmer add a new ambulatory specialty's protocols **without
engineering involvement**. Packs are versioned data; the deterministic engine loads them.
Nothing here introduces a model-driven clinical decision — that invariant (`gaps.md §1`) is
non-negotiable.

## The three moves

### 1. Make sure every marker exists in the catalog
A pack rule fires on a canonical marker. If your protocol needs a marker not yet in
`packages/terminology/clinara_terminology/markers.py`, add it there first — a pure data change:

- Add a `CanonicalMarker` enum member.
- Add a `MARKER_SPECS` entry: canonical unit, default reference range, display name, and the
  `fact_alias` the rules read (e.g. `lab.tsh`). `LAB_FACT_ALIAS` is derived automatically.
- Add seed `LOINC_MAP` codes so real feeds resolve the marker.
- Add unit conversions in `units.py` if the marker arrives in alternate units.
- If — and only if — the marker has a conventional adult **panic** value, add a
  `CRITICAL_THRESHOLDS` entry in `clinara_protocol_engine/critical.py`. This is the
  un-weakenable floor; keep pack rules bounded *above/below* it.

### 2. Author the pack YAML
Create `clinical/protocols/specialties/<panel>.yaml`. Shape:

```yaml
specialty: <pack key>          # the pack's identity (a panel, e.g. "thyroid")
display_name: Thyroid
version: 1
evidence: ["<guideline citations>"]
parameters:                    # practice-customizable thresholds, with defaults
  tsh_upper: 4.5
rules:
  - id: tsh_subclinical
    version: 1
    marker: tsh
    scope: {specialties: [endocrinology, primary_care, ...]}   # which specialties it serves
    when:
      all:
        - {fact: lab.tsh, operator: greater_than, value: {param: tsh_upper}}
        - {fact: lab.tsh, operator: less_than, value: {param: tsh_overt}}
    then: {classification: routine_follow_up, recommended_action: routine_follow_up,
           reason_codes: [TSH_SUBCLINICAL_HYPOTHYROID]}
    safety: {requires_manual_review: false, excluded_when: [patient.pediatric_patient]}
test_cases:                    # required — the activation gate runs these
  - {name: flags, marker: tsh, specialty: endocrinology, facts: {lab.tsh: 6.5},
     expected: routine_follow_up}
  - {name: normal_silent, marker: tsh, specialty: endocrinology, facts: {lab.tsh: 2.0},
     expected: normal}
```

Rules:
- **Parameterize thresholds** with `{param: <name>}`. Anything a practice might reasonably retune
  (targets, upper/lower limits) should be a parameter, not a literal.
- **Bound rules away from the critical floor.** A band whose values could be critical must exclude
  the critical zone (e.g. `hemoglobin >= 6.0 and < 8.0`), so a critical value escalates in the
  engine and no pack rule claims a non-critical outcome for it.
- **Every pack must declare required test cases**, including at least one negative ("silent")
  case and, for markers with a critical band, a `critical_escalation` case.
- List every specialty the pack serves in each rule's `scope.specialties`. Coverage is computed
  from these lists; a specialty in `domains/specialties/catalog.py` with no scoped rule fails the
  coverage test.

### 3. Register the specialty (if new) and validate
- Add the specialty to `AMBULATORY_SPECIALTIES` in `domains/specialties/catalog.py`.
- Run the gate: `pytest apps/api/tests/test_phase10_specialties.py`. It asserts every pack passes
  `validate_pack` (bind → parse → `assert_cannot_weaken_safety` → required tests) and that every
  registered specialty is covered. `services.validate_all()` / `coverage_report()` are the same
  checks you can run in a shell.

## Per-practice customization (no code change)
A practice retunes a threshold through the API — the override is stored as data and re-validated
against the full pack gate before it can go live:

```
POST /api/v1/specialties/packs/thyroid/thresholds  {"parameter": "tsh_upper", "value": 4.0}
```

An override that would down-classify a critical value, break a required test case, or name an
undeclared parameter is rejected (HTTP 422). Reset with
`POST /api/v1/specialties/packs/thyroid/thresholds/reset`.

## What you never do
- Never edit the engine (`clinara_protocol_engine`) to add a specialty. If you think you need to,
  the design is wrong — reach for a catalog entry or a pack rule instead.
- Never weaken a critical threshold to make a rule "work." Criticals are the floor.
- Never author a rule whose outcome depends on free-text or a model judgement. Rules read
  structured facts only.
