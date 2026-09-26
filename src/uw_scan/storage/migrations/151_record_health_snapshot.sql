-- 151_record_health_snapshot.sql — persisted per-table record-health counts,
-- plus BRIN indexes on the timestamp column the record-health sweep filters on.
--
-- /api/health?record_window_hours=... used to run COUNT(*) / COUNT(DISTINCT
-- ticker) / MAX(ts) over ~25 tables on every HealthPanel poll (every 5 s, every
-- page). Over 31 days of prod pg_stat_statements that was 17,720 sweeps per
-- table, 6.3 s mean / 262 s max on option_contract_snapshots, ~48 TB of disk
-- reads and ~182,000 s of DB time. The worker job `record_health_snapshot`
-- (uw-0, every 15 min) now computes the raw counts once and upserts them here;
-- the API reads this table and applies the watchlist-size × coverage thresholds
-- at request time, so only RAW counts are stored.
--
-- Runner note: storage/migrate_runner.py requires conn.autocommit=True and sends
-- each statement as its own simple query — it does NOT wrap a file in a
-- transaction. CREATE INDEX CONCURRENTLY is therefore legal here (026/027/035
-- already rely on this) and is used so the one-time BRIN build on the 23 GB
-- option_contract_snapshots does not block its writers during deploy.
-- Caveat of CONCURRENTLY + IF NOT EXISTS: an interrupted build leaves an
-- INVALID index that a re-run skips; DROP it by name and re-run if that happens.
--
-- BRIN list = the record-health rule tables (timestamp column `inserted_at`,
-- per storage/health._discover_record_health_rules) that are large and whose
-- inserted_at tracks physical order (pg_stats correlation 0.93-1.00 on the
-- local DB). Left out: technical_daily (its nightly upsert rewrites inserted_at
-- on historic rows; correlation 0.056, so BRIN could not prune), and
-- exposures_summary / option_chain_per_strike (no ticker + inserted_at/updated_at
-- column pair, so they are not record-health rule tables at all).
--
-- Idempotent: IF NOT EXISTS throughout.

SET search_path TO uw_scan, public;

CREATE TABLE IF NOT EXISTS uw_scan.record_health_snapshot (
    table_name     text        PRIMARY KEY,
    window_start   timestamptz NOT NULL,
    actual_rows    int         NOT NULL,
    actual_tickers int         NOT NULL,
    latest_at      timestamptz NULL,
    computed_at    timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_option_contract_snapshots_inserted_at_brin
    ON uw_scan.option_contract_snapshots USING brin (inserted_at);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_greeks_by_expiry_strike_inserted_at_brin
    ON uw_scan.greeks_by_expiry_strike USING brin (inserted_at);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_exposures_by_expiry_strike_inserted_at_brin
    ON uw_scan.exposures_by_expiry_strike USING brin (inserted_at);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_option_surface_grid_daily_inserted_at_brin
    ON uw_scan.option_surface_grid_daily USING brin (inserted_at);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_interpolated_iv_snapshots_inserted_at_brin
    ON uw_scan.interpolated_iv_snapshots USING brin (inserted_at);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_skew_swing_greeks_inserted_at_brin
    ON uw_scan.skew_swing_greeks USING brin (inserted_at);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_oi_by_strike_inserted_at_brin
    ON uw_scan.oi_by_strike USING brin (inserted_at);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_iv_term_snapshots_inserted_at_brin
    ON uw_scan.iv_term_snapshots USING brin (inserted_at);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_max_pain_by_expiry_inserted_at_brin
    ON uw_scan.max_pain_by_expiry USING brin (inserted_at);
