-- 101_technical_daily.sql
--
-- Per-(ticker, session) technicals snapshot for the /stock Technicals tab.
-- Nightly technical_daily_refresh recomputes the full series from apex daily
-- bars and upserts every row (idempotent). detail + forward_returns JSONB are
-- populated ONLY on each ticker's latest row (older rows NULLed on refresh).
-- Prices are DOUBLE PRECISION by design: chart-grade series, not money math.
-- Idempotent.

SET search_path TO uw_scan, public;

BEGIN;

CREATE TABLE IF NOT EXISTS uw_scan.technical_daily (
    ticker            TEXT NOT NULL,
    as_of             DATE NOT NULL,
    close             DOUBLE PRECISION,
    sma20             DOUBLE PRECISION,
    sma50             DOUBLE PRECISION,
    sma200            DOUBLE PRECISION,
    z_vs_200dma       DOUBLE PRECISION,
    z_band            TEXT,
    sma200_slope_ann  DOUBLE PRECISION,
    slope_regime      TEXT,
    rsi14             DOUBLE PRECISION,
    macd_hist_atr     DOUBLE PRECISION,
    rs_ratio          DOUBLE PRECISION,
    bars_n            INTEGER,
    detail            JSONB,          -- latest row only: kinematics/sigmoid/distribution/rsi/macd/rs/composite
    forward_returns   JSONB,          -- latest row only: band x horizon conditioning table
    inserted_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (ticker, as_of)
);

CREATE INDEX IF NOT EXISTS ix_technical_daily_asof
    ON uw_scan.technical_daily (as_of DESC);

COMMIT;
