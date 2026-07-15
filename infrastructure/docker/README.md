# Docker assets

- `postgres-init/` — SQL run on first `docker compose up`. Creates the non-superuser
  `clinara_app` role so PostgreSQL RLS is enforced locally (owners/superusers bypass RLS).

Application images live with their apps: `apps/api/Dockerfile`, `apps/web/Dockerfile`.
The local stack is defined in the repo-root `docker-compose.yml`.
