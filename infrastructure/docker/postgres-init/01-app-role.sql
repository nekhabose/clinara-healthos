-- Local bootstrap: create the non-superuser application role so Row-Level Security is
-- actually enforced (superusers and table owners bypass RLS). Production provisions the
-- equivalent role via Terraform against RDS.
DO $$
BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'clinara_app') THEN
    CREATE ROLE clinara_app LOGIN PASSWORD 'clinara_app';
  END IF;
END
$$;

GRANT CONNECT ON DATABASE clinara TO clinara_app;
GRANT USAGE ON SCHEMA public TO clinara_app;
ALTER DEFAULT PRIVILEGES IN SCHEMA public
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO clinara_app;
ALTER DEFAULT PRIVILEGES IN SCHEMA public
  GRANT USAGE, SELECT ON SEQUENCES TO clinara_app;
