-- 155_cockpit_query_indexes.sql — btree indexes for the cockpit request path.
--
-- /api/cockpit/{SPY,QQQ}/dealer took ~47 s on prod (2026-10-03) and the
-- Next.js /api rewrite proxy cuts at 30 s, so the page saw HTTP 500. Per-SQL
-- timing on the mini: the latest-source-date lookup 18.5 s, the flow-colour
-- lookback 21.5 s, the OI-change read 5.7 s, each a Parallel Seq Scan of a
-- 3-7 GB table filtered on (ticker, date) with no matching index. The same
-- lookups also back /cockpit/{T}/state and the other cockpit tabs.
--
-- Runner note (see 151): the runner uses autocommit and one statement per
-- query, so CONCURRENTLY is legal and writers are not blocked. On the mini
-- these were pre-built by hand before the release, so the api's boot-time
-- migrate finds them and skips. An interrupted CONCURRENTLY build leaves an
-- INVALID index that IF NOT EXISTS then skips: DROP it by name and re-run.
--
-- Idempotent: IF NOT EXISTS throughout.

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_greeks_by_expiry_strike_ticker_market_date
    ON uw_scan.greeks_by_expiry_strike (ticker, market_date);

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_exposures_by_expiry_strike_ticker_market_date
    ON uw_scan.exposures_by_expiry_strike (ticker, market_date);

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_iv_term_snapshots_ticker_market_date
    ON uw_scan.iv_term_snapshots (ticker, market_date);

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_interpolated_iv_snapshots_ticker_market_date
    ON uw_scan.interpolated_iv_snapshots (ticker, market_date);

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_flow_events_ticker_created_at
    ON uw_scan.flow_events (ticker, created_at);

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_oi_change_events_underlying_curr_date
    ON uw_scan.oi_change_events (underlying_symbol, curr_date);
