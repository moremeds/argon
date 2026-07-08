-- 102_technical_daily_metrics.sql
--
-- Per-session derived-metric history for the Technicals detail tiles. The
-- nightly refresh now computes cheap rolling metrics (return distribution,
-- RSI z/slope, MACD slope, MA-kinematics slopes, alignment) for EVERY session
-- and stores them here as one JSONB blob per row, so each detail tile can
-- sparkline its own past. Sigmoid stays latest-only (curve_fit per row is too
-- expensive to backfill). Idempotent.

SET search_path TO uw_scan, public;

BEGIN;

ALTER TABLE uw_scan.technical_daily
    ADD COLUMN IF NOT EXISTS metrics JSONB;

COMMIT;
