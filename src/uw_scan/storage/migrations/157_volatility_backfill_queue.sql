-- 157_volatility_backfill_queue.sql — let volatility_backfill_status hold a
-- durable 'queued' state.
--
-- GET /stock/{t}/volatility/series used to start the UW backfill as a FastAPI
-- BackgroundTask: an API restart lost it, and its UW spend ran outside the
-- budget governor. The GET now upserts status='queued' (the ticker PK keeps it
-- to one row per ticker) and the uw-0 worker's volatility_backfill_tick claims
-- it. started_at already exists and is the stale-'running' requeue key.
--
-- Idempotent: every API boot re-runs this file, so drop the CHECK if present
-- and add the widened one, in one transaction. No DML.

SET search_path TO uw_scan, public;

BEGIN;

ALTER TABLE uw_scan.volatility_backfill_status
  DROP CONSTRAINT IF EXISTS volatility_backfill_status_status_check;

ALTER TABLE uw_scan.volatility_backfill_status
  ADD CONSTRAINT volatility_backfill_status_status_check
  CHECK (status IN ('queued', 'running', 'ready', 'failed'));

COMMENT ON TABLE uw_scan.volatility_backfill_status
    IS 'Durable queue + state machine for the on-demand volatility backfill (queued/running/ready/failed).';

COMMIT;
