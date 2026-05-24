-- 054_rates_cftc_tff.sql — CFTC Traders in Financial Futures for Treasury rates.
-- Idempotent: CREATE TABLE IF NOT EXISTS / CREATE INDEX IF NOT EXISTS.

SET search_path TO uw_scan, public;

CREATE TABLE IF NOT EXISTS uw_scan.rates_cftc_tff_weekly (
  contract_code        TEXT        NOT NULL,
  contract_name        TEXT        NOT NULL,
  commodity_name       TEXT        NULL,
  tenor_bucket         TEXT        NOT NULL,
  obs_date             DATE        NOT NULL,
  release_date         DATE        NOT NULL,
  open_interest        NUMERIC     NULL,
  dealer_long          NUMERIC     NULL,
  dealer_short         NUMERIC     NULL,
  dealer_net           NUMERIC     NULL,
  asset_mgr_long       NUMERIC     NULL,
  asset_mgr_short      NUMERIC     NULL,
  asset_mgr_net        NUMERIC     NULL,
  lev_money_long       NUMERIC     NULL,
  lev_money_short      NUMERIC     NULL,
  lev_money_net        NUMERIC     NULL,
  other_rept_long      NUMERIC     NULL,
  other_rept_short     NUMERIC     NULL,
  other_rept_net       NUMERIC     NULL,
  dealer_net_pct_oi    NUMERIC     NULL,
  asset_mgr_net_pct_oi NUMERIC     NULL,
  lev_money_net_pct_oi NUMERIC     NULL,
  as_of                TIMESTAMPTZ NOT NULL,
  source_url           TEXT        NULL,
  PRIMARY KEY (contract_code, obs_date, as_of)
);

CREATE INDEX IF NOT EXISTS idx_rates_cftc_tff_latest
  ON uw_scan.rates_cftc_tff_weekly (obs_date DESC, contract_code, as_of DESC);

CREATE INDEX IF NOT EXISTS idx_rates_cftc_tff_release
  ON uw_scan.rates_cftc_tff_weekly (release_date DESC, contract_code, as_of DESC);
