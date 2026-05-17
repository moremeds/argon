-- 037_gold_macro_series.sql — Phase A1 (Gold).
-- Macro series ingested from FRED, GPR, and computed transforms.
-- PIT-disciplined: (series_id, obs_date, as_of) PK so re-pulls store new vintages.
-- Idempotent: CREATE TABLE IF NOT EXISTS / CREATE INDEX IF NOT EXISTS.

SET search_path TO uw_scan, public;

CREATE TABLE IF NOT EXISTS uw_scan.macro_series_daily (
  series_id     TEXT        NOT NULL,
  obs_date      DATE        NOT NULL,
  value         NUMERIC     NOT NULL,
  as_of         TIMESTAMPTZ NOT NULL,
  release_date  DATE        NULL,
  source        TEXT        NOT NULL,
  source_url    TEXT        NULL,
  PRIMARY KEY (series_id, obs_date, as_of)
);

CREATE INDEX IF NOT EXISTS idx_macro_series_daily_lookup
  ON uw_scan.macro_series_daily (series_id, obs_date DESC, as_of DESC);

CREATE TABLE IF NOT EXISTS uw_scan.macro_series_monthly (
  series_id     TEXT        NOT NULL,
  obs_month     DATE        NOT NULL,
  value         NUMERIC     NOT NULL,
  as_of         TIMESTAMPTZ NOT NULL,
  release_date  DATE        NULL,
  source        TEXT        NOT NULL,
  source_url    TEXT        NULL,
  PRIMARY KEY (series_id, obs_month, as_of)
);

CREATE INDEX IF NOT EXISTS idx_macro_series_monthly_lookup
  ON uw_scan.macro_series_monthly (series_id, obs_month DESC, as_of DESC);
