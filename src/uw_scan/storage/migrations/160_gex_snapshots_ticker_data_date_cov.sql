-- 160_gex_snapshots_ticker_data_date_cov.sql — covering index for the GEX
-- 90-day history (storage/gex.py fetch_metrics_history).
--
-- /api/regime/gex spent ~95% of its time in that query: a backward scan of
-- ix_gex_data_date that filtered out every other ticker and detoasted the
-- payload of every kept row (pg_stat_statements on the mini since 2026-08-27:
-- 2,678 calls, mean 2.0 s, max 56.5 s). With this index the inner DISTINCT ON
-- is an Index Only Scan and only the chosen <= 90 rows touch the heap.
--
-- Pre-built on the mini by hand with CONCURRENTLY on 2026-10-05, so the api's
-- boot-time migrate finds it and skips. Runner note (see 151/155): autocommit,
-- one statement per query, so CONCURRENTLY is legal; an interrupted build
-- leaves an INVALID index that IF NOT EXISTS skips: DROP it by name and re-run.
--
-- Idempotent: IF NOT EXISTS.

CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_gex_snapshots_ticker_data_date_cov
    ON uw_scan.gex_snapshots (ticker, data_date DESC, scanned_at DESC)
    INCLUDE (id, level_gex_flip_strike, iv_30d, vol_pc);
