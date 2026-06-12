-- 070_regime_snapshot_basis.sql
--
-- Live CRI/VCG snapshots share cri_snapshots / vcg_snapshots with the EOD
-- scans (mirrors how gex_snapshots serves both the daily HistoryChart and
-- the intraday 5-session chart). `basis` distinguishes the two write paths:
--   'eod'  — hourly :20/:25 scans off vol_index_daily daily closes (canonical)
--   'live' — 5-min regime_live_scan rows with WS quotes spliced as today's
--            provisional close (slim payload: no history / spy_closes arrays)
-- New generated columns expose every series the intraday/daily multi-panel
-- charts need without a JSONB parse (gex_snapshots pattern).
-- Idempotent.

SET search_path TO uw_scan, public;

BEGIN;

ALTER TABLE uw_scan.cri_snapshots
    ADD COLUMN IF NOT EXISTS basis TEXT NOT NULL DEFAULT 'eod';
ALTER TABLE uw_scan.cri_snapshots
    ADD COLUMN IF NOT EXISTS spx NUMERIC(12,2)
        GENERATED ALWAYS AS ((payload->>'spy')::numeric) STORED;
ALTER TABLE uw_scan.cri_snapshots
    ADD COLUMN IF NOT EXISTS vix3m NUMERIC(8,2)
        GENERATED ALWAYS AS ((payload->>'vix3m')::numeric) STORED;
ALTER TABLE uw_scan.cri_snapshots
    ADD COLUMN IF NOT EXISTS vrp NUMERIC(8,2)
        GENERATED ALWAYS AS ((payload->>'vrp')::numeric) STORED;
ALTER TABLE uw_scan.cri_snapshots
    ADD COLUMN IF NOT EXISTS vix_zscore_30d NUMERIC(8,2)
        GENERATED ALWAYS AS ((payload->>'vix_zscore_30d')::numeric) STORED;
ALTER TABLE uw_scan.cri_snapshots
    ADD COLUMN IF NOT EXISTS vix_vix3m_ratio NUMERIC(8,3)
        GENERATED ALWAYS AS ((payload->>'vix_vix3m_ratio')::numeric) STORED;

ALTER TABLE uw_scan.vcg_snapshots
    ADD COLUMN IF NOT EXISTS basis TEXT NOT NULL DEFAULT 'eod';
ALTER TABLE uw_scan.vcg_snapshots
    ADD COLUMN IF NOT EXISTS residual NUMERIC(14,6)
        GENERATED ALWAYS AS (((payload->'signal')->>'residual')::numeric) STORED;
ALTER TABLE uw_scan.vcg_snapshots
    ADD COLUMN IF NOT EXISTS credit_5d_return NUMERIC(10,3)
        GENERATED ALWAYS AS (((payload->'signal')->>'credit_5d_return_pct')::numeric) STORED;
ALTER TABLE uw_scan.vcg_snapshots
    ADD COLUMN IF NOT EXISTS beta1 NUMERIC(14,6)
        GENERATED ALWAYS AS (((payload->'signal')->>'beta1_vvix')::numeric) STORED;
ALTER TABLE uw_scan.vcg_snapshots
    ADD COLUMN IF NOT EXISTS beta2 NUMERIC(14,6)
        GENERATED ALWAYS AS (((payload->'signal')->>'beta2_vix')::numeric) STORED;

CREATE INDEX IF NOT EXISTS ix_cri_basis_scanned_at
    ON uw_scan.cri_snapshots (basis, scanned_at DESC);
CREATE INDEX IF NOT EXISTS ix_vcg_basis_scanned_at
    ON uw_scan.vcg_snapshots (basis, scanned_at DESC);

COMMIT;
