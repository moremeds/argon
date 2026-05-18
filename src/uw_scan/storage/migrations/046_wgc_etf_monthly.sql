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

CREATE OR REPLACE VIEW uw_scan.wgc_etf_monthly_canonical AS
WITH source_revisions AS (
  SELECT
    source_url,
    max(obs_date) AS revision_obs_date
  FROM uw_scan.wgc_etf_monthly
  GROUP BY source_url
)
SELECT DISTINCT ON (w.ticker, w.obs_date)
  w.ticker,
  w.obs_date,
  w.fund_name,
  w.fund_type,
  w.region,
  w.country,
  w.gold_price_usd_oz,
  w.aggregate_ounces,
  w.aggregate_holdings_tonnes,
  w.aggregate_value_usd,
  w.holdings_tonnes,
  w.demand_tonnes,
  w.flow_usd_mn,
  w.source_url,
  w.source_label,
  w.as_of,
  w.source
FROM uw_scan.wgc_etf_monthly w
JOIN source_revisions s ON s.source_url = w.source_url
ORDER BY
  w.ticker,
  w.obs_date,
  s.revision_obs_date DESC,
  w.as_of DESC,
  w.source_url DESC;
