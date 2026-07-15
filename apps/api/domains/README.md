# Domain modules (modular monolith — spec §7.4)

These are the "apps" from spec §7.4. They live under `domains/` (not the repo-root
`apps/`, which holds deployables) to avoid a naming collision. Each module is a Django
app labeled by its short name (e.g. `identity`).

## Standard module layout

```
domains/<name>/
  apps.py       AppConfig (name = "domains.<name>", label = "<name>")
  models.py     domain persistence models (inherit core.models.TenantScopedModel)
  services.py   the ONLY public entry point other modules may call
  events.py     domain events this module publishes (via core.outbox.publish_event)
  README.md     boundary + responsibilities
```

## Boundary rules

- A module owns its models. Other modules must **not** import them directly.
- Cross-module access is through `services.py` interfaces and explicit domain events.
- Clinical decision logic never lives in controllers/serializers.
- Integration-specific logic never leaks into protocol logic.
- Tenant customization is data-driven — never code branches.

## Activation status

| Module | Phase | Status in Phase 0 |
|---|---|---|
| `identity`, `tenants`, `audit`, `operations` | 0 | **Active** (in `INSTALLED_APPS`) |
| `terminology`, `clinical_data`, `context`, `protocols`, `workflows`, `generation` | 1 | Boundary stub |
| `integrations`, `delivery` | 3 | Boundary stub |
| `safety` | cross-phase | Boundary stub |
| `feedback`, `analytics` | 6 | Boundary stub |

Stubs are commented out in `clinara/settings/base.py` and uncommented as each phase lands.
