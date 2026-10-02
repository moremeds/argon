-- mcp_role.sql — create the read-only `argon_mcp` login role + its grants.
--
-- Run ONCE per database, as a superuser:
--   prod (mini):  psql -U postgres -d option_wizard       -f scripts/ops/mcp_role.sql
--   local smoke:  psql -d option_wizard_local             -f scripts/ops/mcp_role.sql
--
-- The role is created with NO password — the operator sets it out-of-band
-- (`\password argon_mcp` inside psql, or ALTER ROLE … PASSWORD) and the value
-- goes into /opt/argon/.env as MCP_DATABASE_URL. A password is never
-- committed here.
--
-- Rights: SELECT on every existing + future uw_scan table (read-only over the
-- whole business surface), and exactly two writes — mcp_access_log (one row
-- per tool call) and mcp_event_cursor (per-token event replay cursor). A
-- `SELECT` statement that mutates via CTE/function still fails: the role has
-- no INSERT/UPDATE/DELETE/EXECUTE elsewhere.
--
-- Idempotent: DO-block guards CREATE ROLE; GRANTs are re-runnable.

SET search_path TO uw_scan, public;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'argon_mcp') THEN
        CREATE ROLE argon_mcp LOGIN;
    END IF;
END
$$;

GRANT USAGE ON SCHEMA uw_scan TO argon_mcp;
GRANT SELECT ON ALL TABLES IN SCHEMA uw_scan TO argon_mcp;

-- Tables argon_app (the migration owner) creates later stay readable.
ALTER DEFAULT PRIVILEGES FOR ROLE argon_app IN SCHEMA uw_scan
    GRANT SELECT ON TABLES TO argon_mcp;

-- The only two writes.
GRANT INSERT ON uw_scan.mcp_access_log TO argon_mcp;
GRANT SELECT, INSERT, UPDATE ON uw_scan.mcp_event_cursor TO argon_mcp;

-- mcp_access_log.id is bigserial → its default nextval() needs sequence
-- USAGE. mcp_event_cursor's PK is the token label — it has no sequence.
GRANT USAGE ON SEQUENCE uw_scan.mcp_access_log_id_seq TO argon_mcp;
