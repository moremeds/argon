-- 034_remove_spx_from_watchlist.sql — reverse 033.
--
-- Adding SPX to the watchlist (migration 033) made flow_data_refresh and
-- full_scan ingest its flow_alerts and option_chain_per_strike, which closed
-- two cockpit data gaps. But it also exposed SPX to every watchlist-driven
-- view (landing page cards, scanner, sector grouping), which assumes ETF/stock
-- semantics SPX (a cash index whose options trade as SPXW) does not satisfy.
--
-- Roll SPX back out of the watchlist. The Cockpit still ingests SPX series
-- data via cockpit_daily_snapshot (which iterates settings.cockpit_tickers,
-- not this table), so RV/IV/skew/greeks/exposures and per-strike OI keep
-- flowing. Trade-off: SPX flow_events stay empty until a different ingestion
-- path is added — accepted intentionally.

-- Soft-delete: set removed_at instead of DELETE. The watchlist_card table
-- has a FK on watchlist.ticker, and list_watchlist_cards already filters
-- WHERE removed_at IS NULL, so this is the existing remove pattern.

BEGIN;

UPDATE uw_scan.watchlist
   SET removed_at = NOW()
 WHERE ticker = 'SPX' AND removed_at IS NULL;

COMMIT;
