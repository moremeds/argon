-- 038_vol_index_daily.sql
--
-- CBOE volatility index daily OHLC, sourced from the local parquet lake.
-- Covers SPX (filling the UW /ohlc/1d gap for indices) and the vol complex
-- (VIX, VIX3M, VVIX, COR1M, COR3M, OVX, RVX, VXN, VXEEM, etc.).
-- Idempotent.

SET search_path TO uw_scan, public;

BEGIN;

CREATE TABLE IF NOT EXISTS uw_scan.vol_index_daily (
    symbol      TEXT NOT NULL,
    trade_date  DATE NOT NULL,
    open        NUMERIC(14,4),
    high        NUMERIC(14,4),
    low         NUMERIC(14,4),
    close       NUMERIC(14,4),
    adj_close   NUMERIC(14,4),
    volume      BIGINT,
    PRIMARY KEY (symbol, trade_date)
);

CREATE INDEX IF NOT EXISTS ix_vol_index_symbol_date
    ON uw_scan.vol_index_daily (symbol, trade_date DESC);

COMMIT;
