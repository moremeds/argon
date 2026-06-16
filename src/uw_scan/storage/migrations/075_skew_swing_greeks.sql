-- 075_skew_swing_greeks.sql — Phase-2 increment-1 (swing-DTE greeks source).
-- Per-strike call/put delta for a SWING expiry (~21-60 DTE) per single-name, so the
-- Skew tab's strike-by-delta structure detail can pick wings. The GEX/cockpit
-- exposures_by_expiry_strike table holds front-expiry-only greeks for single-names
-- (only indices get multi-expiry via the cockpit), so this dedicated table avoids a
-- run_id race and keeps the swing chain readable independent of full_scan/cockpit runs.
-- Idempotent. One snapshot per (ticker, market_date, expiry, strike).

SET search_path TO uw_scan, public;

CREATE TABLE IF NOT EXISTS uw_scan.skew_swing_greeks (
  ticker       TEXT NOT NULL,
  market_date  DATE NOT NULL,
  expiry       DATE NOT NULL,
  strike       NUMERIC NOT NULL,
  dte          INTEGER,
  call_delta   NUMERIC,
  put_delta    NUMERIC,
  inserted_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (ticker, market_date, expiry, strike)
);

CREATE INDEX IF NOT EXISTS ix_skew_swing_greeks_ticker_date
  ON uw_scan.skew_swing_greeks (ticker, market_date DESC);

COMMENT ON TABLE uw_scan.skew_swing_greeks
  IS 'Per-strike call/put delta for a swing expiry (~21-60 DTE), single-names only. Source for the Skew tab strike-by-delta structure detail. Refreshed daily by worker/jobs/skew_swing_greeks.skew_swing_greeks_refresh.';
