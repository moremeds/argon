-- 040_gold_cb_reserves.sql — Phase A1 (Gold).
-- Central-bank gold reserves (monthly). WGC is the primary source;
-- INDUSTRY estimates fill in suspended reporters (e.g. Russia post-2022).
-- Bucket classification (strategic_accumulator / tactical_defender / reserve_diversifier)
-- is driven by config in src/uw_scan/cards/structural_flow.py.

SET search_path TO uw_scan, public;

CREATE TABLE IF NOT EXISTS uw_scan.cb_gold_reserves_monthly (
  country_iso3   TEXT        NOT NULL,
  obs_month      DATE        NOT NULL,
  reserves_t     NUMERIC     NULL,
  bucket         TEXT        NOT NULL,
  is_reported    BOOLEAN     NOT NULL DEFAULT TRUE,
  is_estimated   BOOLEAN     NOT NULL DEFAULT FALSE,
  as_of          TIMESTAMPTZ NOT NULL,
  release_date   DATE        NULL,
  source         TEXT        NOT NULL,
  PRIMARY KEY (country_iso3, obs_month, as_of)
);

CREATE INDEX IF NOT EXISTS idx_cb_gold_reserves_bucket
  ON uw_scan.cb_gold_reserves_monthly (bucket, obs_month DESC);

CREATE INDEX IF NOT EXISTS idx_cb_gold_reserves_country
  ON uw_scan.cb_gold_reserves_monthly (country_iso3, obs_month DESC, as_of DESC);
