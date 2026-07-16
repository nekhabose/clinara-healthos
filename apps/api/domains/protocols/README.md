# Protocols — Clinical Rule Studio (Phase 2)

The governed authoring surface that lets clinical experts create, simulate, impact-analyze,
approve, deploy, and roll back clinical logic **with no application code change** (plan
Phase 2; spec §6.5). Rules are versioned declarative artifacts (spec §6.5.3) — the same
`Rule` shape the production engine evaluates — so a simulation runs the *exact* logic that
would run live.

## Layout
- `core.py` — **pure, Django-free** Studio mechanics (exhaustively unit-tested):
  lifecycle state machine (spec §6.5.4), simulation (§6.5.6), impact analysis (§6.5.7),
  conflict detection (§6.4.3), and the `assert_cannot_weaken_safety` guard.
- `models.py` — `Protocol`, `ProtocolVersion`, `RuleTestCase`, `SimulationRun`,
  `Deployment`, `Rollback` (all tenant-scoped → RLS).
- `services.py` — the only entry point: authoring, dual-approval, the activation gate,
  shadow/progressive/full deploy, and rollback. Every mutation is audited + emits events.

## Governed guarantees
- **Legal lifecycle only** — draft → in_review → approved → scheduled → active →
  deprecated/retired/rolled_back. Illegal jumps raise `IllegalTransition`.
- **Activation gate** — a version cannot go live unless it is dual-approved (clinical +
  engineering) and every attached regression test passes.
- **Conflict → suppression** — ambiguous precedence never silently resolves; the deployment
  records `conflicts_suppressed=True`.
- **Un-weakenable safety floor** — a rule that would down-classify a critical value is
  refused (`SafetyViolation`) before it can be stored/deployed. Global safety constraints
  are engine-enforced and physically un-editable here.
- **Config ≠ code** — clinical config deploys through this pipeline, separate from
  application CI/CD (spec §14.3), and ships as a self-describing release bundle.

## Boundary rules (spec §7.4)
- This module owns its own domain models. Other modules must not import them directly.
- Cross-module access goes through `services.py` (the public service interface) only.
- Domain events are explicit and published via the transactional outbox.
- No clinical decision logic in controllers/serializers.
- Tenant customization is data-driven — never code branches.
