-- 158_schema_version.sql — the schema-ready marker workers gate on (I-05).
--
-- There is no migration tracking table: every file re-runs on every API boot.
-- Watchtower ignores depends_on, so a worker can boot NEW code against a DB the
-- api has not migrated yet. migrate_runner.apply_migrations writes the name of
-- the last file it applied into this one-row table after a FULL apply; a worker
-- waits until that name is >= the newest migration file shipped in its own image
-- (worker/schema_gate.py).
--
-- Idempotent: CREATE TABLE IF NOT EXISTS, no data here. The row is written by the
-- runner, never by a migration, so a replay cannot move it.

SET search_path TO uw_scan, public;

CREATE TABLE IF NOT EXISTS uw_scan.schema_version (
  id BOOLEAN PRIMARY KEY DEFAULT TRUE CHECK (id),
  last_migration TEXT NOT NULL,
  applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
