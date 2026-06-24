-- 084_vrp_macro_signal_basis.sql
-- Add a `basis` column to vrp_macro_signal_daily so live (5-min, intraday VIX) and
-- eod (nightly) signal rows coexist, mirroring the cri/vcg_snapshots `basis` pattern
-- (migration 070). Idempotent: column add is guarded; the PK is dropped-then-readded.
-- A live row is a single (name, snapshot_date, 'live') row OVERWRITTEN every 5 min —
-- we intentionally do NOT accumulate an intraday vrp_z series (the weekly signal barely
-- moves intraday). ponytail: single overwritten live row, add intraday history only if
-- a chart ever needs it.
SET search_path TO uw_scan, public;

BEGIN;

ALTER TABLE uw_scan.vrp_macro_signal_daily
    ADD COLUMN IF NOT EXISTS basis TEXT NOT NULL DEFAULT 'eod';

-- existing rows default to 'eod', so (name, snapshot_date, 'eod') stays unique →
-- the PK widening is safe. Always drop-then-add for idempotency.
ALTER TABLE uw_scan.vrp_macro_signal_daily
    DROP CONSTRAINT IF EXISTS vrp_macro_signal_daily_pkey;
ALTER TABLE uw_scan.vrp_macro_signal_daily
    ADD CONSTRAINT vrp_macro_signal_daily_pkey
    PRIMARY KEY (name, snapshot_date, basis);

CREATE INDEX IF NOT EXISTS ix_vrp_macro_signal_basis
    ON uw_scan.vrp_macro_signal_daily (basis, name, snapshot_date DESC);

COMMENT ON COLUMN uw_scan.vrp_macro_signal_daily.basis
    IS 'eod = nightly vrp_macro_signal_refresh; live = 5-min regime_live_scan (intraday VIX -> live vrp_z, rv20/distribution from EOD).';

COMMIT;
