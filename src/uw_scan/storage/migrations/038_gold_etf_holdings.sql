-- 038_gold_etf_holdings.sql — Phase A1 (Gold).
-- Daily gold-ETF holdings for GLD, IAU, GLDM, PHYS.
-- holdings_oz is the canonical unit (tonnes-native sources are converted via × 32150.7).

SET search_path TO uw_scan, public;

CREATE TABLE IF NOT EXISTS uw_scan.etf_holdings_daily (
  ticker         TEXT        NOT NULL,
  obs_date       DATE        NOT NULL,
  holdings_oz    NUMERIC     NULL,
  shares_out     NUMERIC     NULL,
  nav_per_share  NUMERIC     NULL,
  premium_pct    NUMERIC     NULL,
  as_of          TIMESTAMPTZ NOT NULL,
  source         TEXT        NOT NULL,
  PRIMARY KEY (ticker, obs_date, as_of)
);

CREATE INDEX IF NOT EXISTS idx_etf_holdings_daily_lookup
  ON uw_scan.etf_holdings_daily (ticker, obs_date DESC, as_of DESC);
