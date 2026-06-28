SET search_path TO uw_scan, public;

-- EOD market-tide slope/sentiment, one row per session — backtest material for
-- "does the day's spread slope predict forward returns?". Computed from
-- market_tide_snapshots by reports/market_tide_sentiment.compute_sentiment.

CREATE TABLE IF NOT EXISTS market_tide_sentiment_daily (
    data_date       DATE PRIMARY KEY,
    state           TEXT NOT NULL,          -- BULLISH | BEARISH | BALANCED | WARMING_UP
    magnitude       TEXT NOT NULL,          -- FLAT | LEANING | STRONG
    driver          TEXT NOT NULL,
    momentum        TEXT NOT NULL,
    spread          NUMERIC(20, 2),         -- EOD S = NCP - NPP ($)
    session_slope   NUMERIC(20, 2),         -- $/hr
    recent_slope    NUMERIC(20, 2),         -- $/hr
    trend_strength  NUMERIC(6, 4),          -- |displacement| / range, 0..1
    volume_confirms BOOLEAN,
    bars            INT NOT NULL,
    computed_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);
