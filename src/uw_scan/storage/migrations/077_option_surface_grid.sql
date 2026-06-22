-- Durable full-chain per-strike IV/greeks grid, forward-accumulated nightly from UW
-- /greeks. UNLIKE greeks_by_expiry_strike, this table has NO run_id FK and is NEVER
-- cascade-deleted — it is the permanent archive that makes future SVI/dislocation/
-- curvature work possible (UW returns 403 for per-strike history beyond ~30 days, so the
-- surface can only be accumulated going forward — every uncaptured night is lost).
-- Idempotent. One snapshot per (ticker, market_date, expiry, strike).

SET search_path TO uw_scan, public;

CREATE TABLE IF NOT EXISTS uw_scan.option_surface_grid_daily (
  ticker          TEXT NOT NULL,
  market_date     DATE NOT NULL,
  expiry          DATE NOT NULL,
  strike          NUMERIC NOT NULL,
  call_iv         NUMERIC,
  put_iv          NUMERIC,
  call_delta      NUMERIC,
  put_delta       NUMERIC,
  call_gamma      NUMERIC,
  put_gamma       NUMERIC,
  call_vega       NUMERIC,
  put_vega        NUMERIC,
  call_theta      NUMERIC,
  put_theta       NUMERIC,
  call_vanna      NUMERIC,
  put_vanna       NUMERIC,
  call_charm      NUMERIC,
  put_charm       NUMERIC,
  underlying_spot NUMERIC,
  source          TEXT NOT NULL DEFAULT 'uw_greeks',
  inserted_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (ticker, market_date, expiry, strike)
);

CREATE INDEX IF NOT EXISTS ix_option_surface_grid_ticker_date
  ON uw_scan.option_surface_grid_daily (ticker, market_date DESC);

COMMENT ON TABLE uw_scan.option_surface_grid_daily
  IS 'Durable full-chain per-strike IV/greeks grid, forward-accumulated nightly from UW /greeks by worker/jobs/option_surface_capture. NO run_id FK by design — permanent archive (UW blocks per-strike history beyond ~30 days). One row per (ticker, market_date, expiry, strike).';
