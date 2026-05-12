-- 007_aggregates_column.sql — per-run MarketAggregates JSONB on scan_runs.
-- Idempotent.

SET search_path TO uw_scan, public;

ALTER TABLE uw_scan.scan_runs
  ADD COLUMN IF NOT EXISTS aggregates JSONB;
COMMENT ON COLUMN uw_scan.scan_runs.aggregates IS
  'Per-ticker bulk-screener aggregates (call/put OI/volume, PCR, IV30d). Pydantic MarketAggregates payload.';
