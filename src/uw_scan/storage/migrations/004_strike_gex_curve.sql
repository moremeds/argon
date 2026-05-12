-- 004_strike_gex_curve.sql — persist per-strike, per-expiry GEX as JSONB on each scan run.
-- Idempotent; rows pre-004 stay valid (column is nullable).

SET search_path TO uw_scan, public;

ALTER TABLE uw_scan.scan_runs
  ADD COLUMN IF NOT EXISTS strike_gex_curve JSONB;
COMMENT ON COLUMN uw_scan.scan_runs.strike_gex_curve IS
  'Per-strike, per-expiry GEX curve. Array of {strike, expiry, net_gex, call_gex, put_gex}. Nullable; old rows pre-004 stay valid.';
