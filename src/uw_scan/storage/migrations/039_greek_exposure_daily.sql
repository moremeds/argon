-- 039_greek_exposure_daily.sql
--
-- Daily history of UW's /greek-exposure for each watchlist ticker. The endpoint
-- returns ~250 trailing daily rows in every call; we persist the tail so the
-- regime page can render a 90-day history chart without re-fetching.
-- Idempotent.

SET search_path TO uw_scan, public;

BEGIN;

-- Columns mirror UW's /greek-exposure (history) payload exactly:
--   date, call_gex, put_gex, call_delta, put_delta
-- Computed convenience columns: net_gex, net_dex.
--
-- NOT stored here (UW doesn't return them in this payload):
--   - gex_flip (per-day): computed from per-strike GEX; we only have
--     today's via /greek-exposure/strike. Historical flip values come
--     from gex_snapshots over time (forward-only).
--   - price/spot: comes from daily_ohlc (ETFs) or vol_index_daily (SPX).
CREATE TABLE IF NOT EXISTS uw_scan.greek_exposure_daily (
    ticker         TEXT NOT NULL,
    trade_date     DATE NOT NULL,
    call_gex       NUMERIC(20,4),
    put_gex        NUMERIC(20,4),
    call_delta     NUMERIC(20,4),
    put_delta      NUMERIC(20,4),
    net_gex        NUMERIC(20,4) GENERATED ALWAYS AS (call_gex + put_gex) STORED,
    net_dex        NUMERIC(20,4) GENERATED ALWAYS AS (call_delta + put_delta) STORED,
    payload        JSONB,
    PRIMARY KEY (ticker, trade_date)
);

CREATE INDEX IF NOT EXISTS ix_greek_exposure_daily_ticker_date
    ON uw_scan.greek_exposure_daily (ticker, trade_date DESC);

COMMIT;
