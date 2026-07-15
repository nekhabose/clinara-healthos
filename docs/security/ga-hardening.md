# Security Hardening — GA (spec §11.4, §10.2, §11)

GA-readiness security controls layered on the Phase 0–6 platform. All are code-expressible and
tested; the operational validations (pen-test, external audit) are checklists driven against
these controls.

## Emergency controls

### Kill switches (`domains/killswitch` — spec §11.4)
Ten scopes, broadest → narrowest: **global, tenant, site, specialty, workflow, protocol,
clinician, model_provider, integration, communication_channel**. A switch at any scope suppresses
automation within it; a broader switch is never overridden by a narrower one; an attempt that
cannot be fully attributed is suppressed (deny-on-ambiguity). Every suppression is explainable
(names the scope/target/reason) and every engage/release is audited + event-published.

### LLM kill-switch validation across all scopes
The generation/classification path selects its provider through `reliability.choose_provider`,
which consults the **live** kill-switch set:
- a `MODEL_PROVIDER` switch removes one provider → failover to the next healthy one;
- a `GLOBAL` switch removes **all** providers → the caller falls back to the deterministic path.
Covered by `test_killswitch_core.test_all_ten_scopes_are_enforceable`,
`test_reliability_core.test_global_kill_switch_leaves_no_provider`, and the service-level
`test_ga_hardening.test_provider_failover_skips_killed_provider`.

### Break-glass access (`identity.breakglass` — spec §10.2)
Emergency elevated access is **time-boxed** (hard cap 1h), **reason-mandatory**, and **always
audited** (grant, use, revoke — even a *denied* request is recorded in its own committed
transaction). Fail-closed: revoked or expired ⇒ no access.

## Platform hardening (production settings)
TLS redirect + HSTS (preload, includeSubDomains), secure/HTTP-only cookies, `nosniff`,
`X-Frame-Options: DENY`, `Referrer-Policy: same-origin`. The production DB role is a
non-superuser so **RLS is enforced** (no local-superuser escape hatch in prod).

## Break-glass / kill-switch penetration-test checklist
- [ ] A GLOBAL kill switch halts automation across every tenant and workflow.
- [ ] A killed model provider is never called; failover picks the next; all-killed → no-LLM path.
- [ ] Break-glass cannot be granted without a reason; cannot exceed the TTL cap; expires on time.
- [ ] Every emergency action appears in the hash-chained audit trail.
- [ ] Cross-tenant access is blocked at the DB (RLS) even as a non-superuser table owner
      (`FORCE ROW LEVEL SECURITY`) — see `tests/test_tenant_isolation.py` (Postgres job).
- [ ] Prompt injection in patient text cannot suppress a deterministic red flag (Phase 5).

## Release gate (spec §13.5)
`core/release_gate.py` + `scripts/release_gate.py` fail the build (fail-closed) unless all eight
§13.5 conditions hold, including cross-tenant isolation and rollback availability. Wired as the
`release-gate` CI job depending on the test + RLS jobs.
