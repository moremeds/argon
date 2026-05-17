-- 042_gold_uw_options.sql — Phase A1 (Gold).
-- Persistence-only in A1; not consumed by A1 compute. Backtest history accumulates
-- from day one so Phase A3 has data to work with.

SET search_path TO uw_scan, public;

CREATE TABLE IF NOT EXISTS uw_scan.uw_gold_options_daily (
  ticker             TEXT        NOT NULL,
  obs_date           DATE        NOT NULL,
  atm_iv_30d         NUMERIC     NULL,
  atm_iv_60d         NUMERIC     NULL,
  put_25d_iv_30d     NUMERIC     NULL,
  call_25d_iv_30d    NUMERIC     NULL,
  skew_25d_30d       NUMERIC     NULL,
  put_call_oi_ratio  NUMERIC     NULL,
  dealer_gamma_est   NUMERIC     NULL,
  as_of              TIMESTAMPTZ NOT NULL,
  PRIMARY KEY (ticker, obs_date, as_of)
);

CREATE INDEX IF NOT EXISTS idx_uw_gold_options_daily_lookup
  ON uw_scan.uw_gold_options_daily (ticker, obs_date DESC, as_of DESC);
