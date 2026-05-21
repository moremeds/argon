-- 052_rates_tables.sql — US rates mirror.
-- FRED-backed observations and durable assembled page snapshots.
-- Idempotent: CREATE TABLE IF NOT EXISTS / CREATE INDEX IF NOT EXISTS.

SET search_path TO uw_scan, public;

CREATE TABLE IF NOT EXISTS uw_scan.rates_observations (
  series_id       TEXT        NOT NULL,
  obs_date        DATE        NOT NULL,
  value           NUMERIC     NOT NULL,
  realtime_start  DATE        NOT NULL,
  realtime_end    DATE        NOT NULL,
  first_seen_at   TIMESTAMPTZ NOT NULL,
  last_seen_at    TIMESTAMPTZ NOT NULL,
  release_date    DATE        NULL,
  source          TEXT        NOT NULL,
  source_url      TEXT        NULL,
  PRIMARY KEY (series_id, obs_date, realtime_start, realtime_end, source)
);

CREATE INDEX IF NOT EXISTS idx_rates_observations_lookup
  ON uw_scan.rates_observations (
    series_id,
    obs_date DESC,
    realtime_start DESC,
    last_seen_at DESC
  );

CREATE TABLE IF NOT EXISTS uw_scan.rates_snapshots (
  snapshot_date    DATE        NOT NULL,
  computed_at      TIMESTAMPTZ NOT NULL,
  payload          JSONB       NOT NULL,
  source_freshness JSONB       NOT NULL DEFAULT '[]'::jsonb,
  PRIMARY KEY (snapshot_date, computed_at)
);

CREATE INDEX IF NOT EXISTS idx_rates_snapshots_latest
  ON uw_scan.rates_snapshots (snapshot_date DESC, computed_at DESC);

CREATE INDEX IF NOT EXISTS idx_rates_snapshots_latest_compute
  ON uw_scan.rates_snapshots (computed_at DESC, snapshot_date DESC);
