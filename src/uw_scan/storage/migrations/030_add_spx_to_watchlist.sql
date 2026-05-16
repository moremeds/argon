-- 030_add_spx_to_watchlist.sql
--
-- Add SPX (S&P 500 cash index, weekly options trade as SPXW symbols) to the
-- watchlist so flow_data_refresh and full_scan ingest its flow_alerts and
-- option_chain_per_strike rows. The Cockpit settings already include SPX in
-- COCKPIT_TICKERS, but cockpit_daily_snapshot only persists greeks/skew/IV/RV;
-- the per-strike chain and flow events come through the watchlist-driven
-- workers and were silently skipped because SPX was missing from this table.

BEGIN;

INSERT INTO uw_scan.watchlist (ticker, sector, sort_rank, pinned, notes)
VALUES ('SPX', 'Index', 100, FALSE,
        'S&P 500 cash index — weekly options listed as SPXW. Cockpit ticker.')
ON CONFLICT (ticker) DO UPDATE
  SET sector     = EXCLUDED.sector,
      sort_rank  = EXCLUDED.sort_rank,
      removed_at = NULL;

COMMIT;
