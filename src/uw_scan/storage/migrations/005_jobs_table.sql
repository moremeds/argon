-- 005_jobs_table.sql — ad-hoc rescan jobs for the Rescan button.
-- Idempotent.

SET search_path TO uw_scan, public;

CREATE EXTENSION IF NOT EXISTS "pgcrypto";  -- for gen_random_uuid()

CREATE TABLE IF NOT EXISTS uw_scan.jobs (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  ticker        TEXT NOT NULL REFERENCES uw_scan.watchlist(ticker),
  status        TEXT NOT NULL CHECK (status IN ('queued','running','done','failed')),
  run_id        BIGINT,
  error         TEXT,
  requested_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  started_at    TIMESTAMPTZ,
  finished_at   TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_jobs_queued
  ON uw_scan.jobs (status, requested_at)
  WHERE status IN ('queued','running');
