-- 025_jobs_claim_token.sql — add per-claim token so mark_job_done/failed can
-- detect when a slow worker tries to update a row that has been requeued and
-- reclaimed under a fresh attempt.
--
-- Background: review 2026-05-16-backend-code-review.md B1 + codex review.
-- The previous status='running' guard is insufficient because a requeued+
-- reclaimed row is also 'running' under a different worker.
--
-- Idempotent: ADD COLUMN IF NOT EXISTS, no DEFAULT change for existing rows
-- (existing 'running' rows get a backfill UUID below).
--
-- Concurrency: ALTER TABLE ... ADD COLUMN IF NOT EXISTS without a non-null
-- default is metadata-only and fast in PG 11+. The backfill UPDATE is bounded
-- by the small set of currently-running jobs (typically <10 rows in practice).

SET search_path TO uw_scan, public;

CREATE EXTENSION IF NOT EXISTS "pgcrypto";

ALTER TABLE uw_scan.jobs
  ADD COLUMN IF NOT EXISTS claim_token UUID;

-- Backfill any rows currently 'running' so the next mark_job_done/failed call
-- has something to match. Idempotent: only touches rows where claim_token IS
-- NULL, so re-running is a no-op once filled.
UPDATE uw_scan.jobs
SET claim_token = gen_random_uuid()
WHERE status = 'running' AND claim_token IS NULL;
