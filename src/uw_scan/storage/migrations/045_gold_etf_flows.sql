-- 045_gold_etf_flows.sql — Gold v2 source re-wire.
-- Daily UW ETF in/outflow rows. This is flow, not absolute bullion holdings:
-- GLD/IAU/GLDM commodity trusts can have empty UW constituent holdings while
-- still publishing share/premium flow rows through /api/etfs/{ticker}/in-outflow.

SET search_path TO uw_scan, public;

CREATE TABLE IF NOT EXISTS uw_scan.etf_flows_daily (
  ticker              TEXT        NOT NULL,
  obs_date            DATE        NOT NULL,
  share_change        NUMERIC     NULL,
  premium_change_usd  NUMERIC     NULL,
  close               NUMERIC     NULL,
  volume              NUMERIC     NULL,
  as_of               TIMESTAMPTZ NOT NULL,
  source              TEXT        NOT NULL,
  PRIMARY KEY (ticker, obs_date, as_of)
);

CREATE INDEX IF NOT EXISTS idx_etf_flows_daily_lookup
  ON uw_scan.etf_flows_daily (ticker, obs_date DESC, as_of DESC);
