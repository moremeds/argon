-- 046_wgc_etf_monthly.sql — Gold v2 WGC ETF historical corpus.
-- Monthly Goldhub ETF workbook rows. Stores per-fund holdings, demand, and
-- fund-flow fields with source workbook lineage so revised workbooks are
-- preserved rather than flattened away.

SET search_path TO uw_scan, public;

CREATE TABLE IF NOT EXISTS uw_scan.wgc_etf_monthly (
  ticker                     TEXT        NOT NULL,
  obs_date                   DATE        NOT NULL,
  fund_name                  TEXT        NULL,
  fund_type                  TEXT        NULL,
  region                     TEXT        NULL,
  country                    TEXT        NULL,
  gold_price_usd_oz          NUMERIC     NULL,
  aggregate_ounces           NUMERIC     NULL,
  aggregate_holdings_tonnes  NUMERIC     NULL,
  aggregate_value_usd        NUMERIC     NULL,
  holdings_tonnes            NUMERIC     NULL,
  demand_tonnes              NUMERIC     NULL,
  flow_usd_mn                NUMERIC     NULL,
  source_url                 TEXT        NOT NULL,
  source_label               TEXT        NULL,
  as_of                      TIMESTAMPTZ NOT NULL,
  source                     TEXT        NOT NULL,
  PRIMARY KEY (ticker, obs_date, source_url)
);

CREATE INDEX IF NOT EXISTS idx_wgc_etf_monthly_lookup
  ON uw_scan.wgc_etf_monthly (ticker, obs_date DESC, as_of DESC);

CREATE INDEX IF NOT EXISTS idx_wgc_etf_monthly_source
  ON uw_scan.wgc_etf_monthly (source_url, obs_date DESC);
