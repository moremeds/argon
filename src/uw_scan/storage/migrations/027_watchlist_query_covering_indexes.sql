-- 027_watchlist_query_covering_indexes.sql — speed up the watchlist endpoint's
-- per-request CTEs that resolve market_cap and aum via raw_payloads.
--
-- Background: review 2026-05-16-backend-code-review.md §10/A2 measured the
-- watchlist endpoint at ~1.6 sec/request, with Parallel Seq Scans on the
-- 62K-row raw_payloads table (FK on audit_id but no auto-created index).
--
-- These three indexes turn the seq scans into index scans. They are NOT
-- covering indexes for the JSONB extract — the heap is still touched for
-- payload_jsonb. Expect a 5-15x speedup, not 100x. If the measured
-- improvement is marginal, the longer-term fix is to materialize a
-- ticker_metadata table and drop the JSONB-extract CTEs entirely.
--
-- Idempotent: CREATE INDEX CONCURRENTLY IF NOT EXISTS. CONCURRENTLY avoids
-- blocking concurrent writes during the build. scripts/migrate.sh runs
-- each file with psql -f in autocommit (no --single-transaction wrapper),
-- so CONCURRENTLY is safe here.

SET search_path TO uw_scan, public;

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_raw_payloads_audit_id
  ON uw_scan.raw_payloads (audit_id);

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_api_request_audit_watchlist_endpoints
  ON uw_scan.api_request_audit (endpoint_slug, run_id, audit_id)
  WHERE endpoint_slug IN ('bulk_screener_stocks', 'etf_info');

-- The DISTINCT ON (ticker) ORDER BY ticker, run_id DESC pattern in both
-- watchlist CTEs benefits from a btree on (ticker, run_id DESC) for scan_runs.
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_scan_runs_ticker_run_desc
  ON uw_scan.scan_runs (ticker, run_id DESC);
