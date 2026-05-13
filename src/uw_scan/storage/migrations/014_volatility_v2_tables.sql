-- 014_volatility_v2_tables.sql — added by Volatility Tab v2.
-- See docs/superpowers/specs/2026-05-13-volatility-tab-v2-design.md §4.2.

BEGIN;

CREATE TABLE IF NOT EXISTS uw_scan.index_ohlc_daily (
    ticker      TEXT NOT NULL,
    market_date DATE NOT NULL,
    open        NUMERIC,
    high        NUMERIC,
    low         NUMERIC,
    close       NUMERIC NOT NULL,
    volume      BIGINT,
    inserted_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (ticker, market_date)
);

COMMENT ON TABLE uw_scan.index_ohlc_daily
    IS 'Daily OHLC for benchmark tickers (SPY, sector ETFs). Seeded by scripts/seed_spy_ohlc.py.';

CREATE TABLE IF NOT EXISTS uw_scan.iv_smile_snapshots (
    ticker      TEXT NOT NULL,
    market_date DATE NOT NULL,
    expiry      DATE NOT NULL,
    strike      NUMERIC NOT NULL,
    iv          NUMERIC,
    inserted_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (ticker, market_date, expiry, strike)
);

COMMENT ON TABLE uw_scan.iv_smile_snapshots
    IS 'Per-strike IV by expiry — source for the smile chart. Derived from greeks endpoint.';

CREATE TABLE IF NOT EXISTS uw_scan.vrp_daily (
    ticker      TEXT NOT NULL,
    market_date DATE NOT NULL,
    iv          NUMERIC,
    rv          NUMERIC,
    vrp         NUMERIC,
    vrp_z_20    NUMERIC,
    inserted_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (ticker, market_date)
);

COMMENT ON TABLE uw_scan.vrp_daily
    IS 'Daily VRP (IV-RV) per ticker with rolling 20d z-score. Persisted derivative.';

CREATE TABLE IF NOT EXISTS uw_scan.stock_analytics_daily (
    ticker      TEXT NOT NULL,
    market_date DATE NOT NULL,
    rvol_21     NUMERIC,
    rvol_pctile NUMERIC,
    spy_corr_21 NUMERIC,
    iv_of_iv_20 NUMERIC,
    inserted_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (ticker, market_date)
);

COMMENT ON TABLE uw_scan.stock_analytics_daily
    IS 'Daily per-stock analytics: realised vol, percentile, SPY correlation, IV-of-IV.';

CREATE TABLE IF NOT EXISTS uw_scan.volatility_backfill_status (
    ticker          TEXT PRIMARY KEY,
    status          TEXT NOT NULL CHECK (status IN ('running','ready','failed')),
    started_at      TIMESTAMPTZ,
    finished_at     TIMESTAMPTZ,
    error_message   TEXT
);

COMMENT ON TABLE uw_scan.volatility_backfill_status
    IS 'State machine for the on-demand volatility backfill (running/ready/failed).';

COMMIT;
