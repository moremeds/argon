-- 035_scan_results_market_cap_index.sql — N6 from backend code review.
-- (Originally numbered 028; renumbered to 035 after rebase against main
-- which had landed 028-034 in the cockpit-matrix branch.)
--
-- The watchlist endpoint's latest_market_caps CTE does:
--   SELECT DISTINCT ON (ticker) ticker, marketcap
--   FROM scan_results
--   WHERE marketcap IS NOT NULL
--   ORDER BY ticker, run_id DESC
-- on every /api/watchlist request. Without a supporting partial index this
-- degrades to a Seq Scan as scan_results grows (one row per ticker per scan).
--
-- Migration 027 added a similar covering index for the scan_runs-based CTEs
-- (latest_screener_sizes / latest_etf_aum) but not for this scan_results CTE.
--
-- Idempotent: CREATE INDEX CONCURRENTLY IF NOT EXISTS. CONCURRENTLY avoids
-- blocking concurrent writes; scripts/migrate.sh runs each file in autocommit
-- (psql -f with ON_ERROR_STOP=1, no transaction wrapper) so CONCURRENTLY is
-- safe here.
--
-- Recovery: if an interrupted CREATE INDEX CONCURRENTLY left an INVALID
-- index, the IF NOT EXISTS clause will silently skip the rebuild on rerun.
-- Verify post-apply with:
--   SELECT indexrelid::regclass, indisvalid FROM pg_index
--   WHERE indexrelid::regclass::text = 'uw_scan.idx_scan_results_ticker_run_marketcap';
-- If indisvalid = f, recover with:
--   DROP INDEX CONCURRENTLY uw_scan.idx_scan_results_ticker_run_marketcap;
-- then rerun this migration.

SET search_path TO uw_scan, public;

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_scan_results_ticker_run_marketcap
  ON uw_scan.scan_results (ticker, run_id DESC)
  WHERE marketcap IS NOT NULL;
