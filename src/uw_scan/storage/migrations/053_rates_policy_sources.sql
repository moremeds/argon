-- 053_rates_policy_sources.sql — Fed policy-event and implied-path sources.
-- Idempotent: CREATE TABLE IF NOT EXISTS / CREATE INDEX IF NOT EXISTS.

SET search_path TO uw_scan, public;

CREATE TABLE IF NOT EXISTS uw_scan.rates_policy_events (
  event_date     DATE        NOT NULL,
  label          TEXT        NOT NULL,
  payload        JSONB       NOT NULL,
  source         TEXT        NOT NULL,
  source_url     TEXT        NULL,
  first_seen_at  TIMESTAMPTZ NOT NULL,
  last_seen_at   TIMESTAMPTZ NOT NULL,
  PRIMARY KEY (event_date, source)
);

CREATE INDEX IF NOT EXISTS idx_rates_policy_events_latest
  ON uw_scan.rates_policy_events (event_date DESC, source);

CREATE TABLE IF NOT EXISTS uw_scan.rates_policy_path (
  snapshot_date  DATE        NOT NULL,
  meeting_date   DATE        NOT NULL,
  payload        JSONB       NOT NULL,
  source         TEXT        NOT NULL,
  first_seen_at  TIMESTAMPTZ NOT NULL,
  last_seen_at   TIMESTAMPTZ NOT NULL,
  PRIMARY KEY (snapshot_date, meeting_date, source)
);

CREATE INDEX IF NOT EXISTS idx_rates_policy_path_latest
  ON uw_scan.rates_policy_path (snapshot_date DESC, meeting_date ASC, source);
