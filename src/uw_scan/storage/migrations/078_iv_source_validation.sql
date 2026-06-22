-- Daily ATM IB-vs-UW IV cross-check (data-quality canary). One row per
-- (ticker, market_date, expiry, strike, right). Written by
-- worker/jobs/option_surface_iv_canary. Idempotent.

SET search_path TO uw_scan, public;

CREATE TABLE IF NOT EXISTS uw_scan.iv_source_validation (
  ticker      TEXT NOT NULL,
  market_date DATE NOT NULL,
  expiry      DATE NOT NULL,
  strike      NUMERIC NOT NULL,
  "right"     TEXT NOT NULL,
  uw_iv       NUMERIC,
  ib_iv       NUMERIC,
  abs_diff    NUMERIC,
  inserted_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (ticker, market_date, expiry, strike, "right")
);

COMMENT ON TABLE uw_scan.iv_source_validation
  IS 'Daily ATM IB-vs-UW IV cross-check (data-quality canary) written by worker/jobs/option_surface_iv_canary.';
