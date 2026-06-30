-- 093_watchlist_ticker_events.sql
--
-- Append-only watchlist lifecycle log for the data gap healer. One row per
-- add/remove event so a ticker's history survives a remove->re-add cycle (a
-- mutable membership row would erase the prior removal). Current status =
-- the latest event per ticker.
--
-- Removed tickers need NO exclusion logic: the healer's denominator is built
-- from the live watchlist, so a removed ticker already drops out. This log
-- exists only to make when/why auditable ("log them in db") and to flag
-- newly-added tickers for backfill (the nightly audit then heals their gaps).
-- Idempotent (CREATE ... IF NOT EXISTS); append-only at runtime.

SET search_path TO uw_scan, public;

BEGIN;

CREATE TABLE IF NOT EXISTS uw_scan.watchlist_ticker_events (
    id         BIGSERIAL PRIMARY KEY,
    ticker     TEXT NOT NULL,
    event      TEXT NOT NULL CHECK (event IN ('added', 'removed')),
    event_date DATE NOT NULL,
    note       TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- latest-event-per-ticker lookups (DISTINCT ON (ticker) ... ORDER BY id DESC)
CREATE INDEX IF NOT EXISTS ix_watchlist_ticker_events_latest
    ON uw_scan.watchlist_ticker_events (ticker, id DESC);

COMMIT;
