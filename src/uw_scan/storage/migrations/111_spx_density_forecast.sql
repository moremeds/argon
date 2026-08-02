-- 111_spx_density_forecast.sql — SPX 1–5 trading-day conditional density cone (signal-lab
-- v13 GJR-GARCH port, verdict PASS) + its prospective shadow log.
-- Idempotent. DISPLAY-ONLY research surface: v13's authorisation ceiling is a fan chart
-- plus forward-in-time logging — rows here must never feed sizing, orders, or alerts.

SET search_path TO uw_scan, public;

CREATE TABLE IF NOT EXISTS uw_scan.spx_density_forecast (
    as_of                  DATE NOT NULL,      -- anchor trade date (close the cone is drawn from)
    h                      SMALLINT NOT NULL,  -- horizon in TRADING days, 1..5
    target_date            DATE NOT NULL,      -- weekday-advance estimate at issue; settled to the actual H-th trading day
    scored_horizon         BOOLEAN NOT NULL,   -- h IN (1,2,3,5): v13 scored only these
    -- cumulative simple-return quantiles, the model's native units
    q05                    NUMERIC NOT NULL,
    q10                    NUMERIC NOT NULL,
    q25                    NUMERIC NOT NULL,
    q50                    NUMERIC NOT NULL,
    q75                    NUMERIC NOT NULL,
    q90                    NUMERIC NOT NULL,
    q95                    NUMERIC NOT NULL,
    -- RiskMetrics EWMA lambda=0.94 arm-A analytic band (the non-inferiority baseline)
    baseline_q05           NUMERIC NOT NULL,
    baseline_q10           NUMERIC NOT NULL,
    baseline_q25           NUMERIC NOT NULL,
    baseline_q50           NUMERIC NOT NULL,
    baseline_q75           NUMERIC NOT NULL,
    baseline_q90           NUMERIC NOT NULL,
    baseline_q95           NUMERIC NOT NULL,
    band80_width           NUMERIC NOT NULL,   -- q90 - q10
    baseline_band80_width  NUMERIC NOT NULL,
    width_ratio            NUMERIC NOT NULL,   -- often > 1: the cone is NOT claimed tighter than EWMA
    anchor_close           NUMERIC NOT NULL,   -- price rendering is anchor_close * (1 + q)
    params_jsonb           JSONB,              -- omega/alpha/gamma/beta + persistence; NULL when fallback_used
    fallback_used          BOOLEAN NOT NULL DEFAULT FALSE,
    origin                 TEXT NOT NULL DEFAULT 'prospective'
                           CHECK (origin IN ('prospective', 'reconstructed')),
    provenance_jsonb       JSONB NOT NULL,     -- panel sha256, series index, seed, agreement-check stats
    realised_return        NUMERIC,            -- filled by the settle pass once the target trading day closes
    inside_band80          BOOLEAN,            -- q10 <= realised <= q90, set with realised_return
    inserted_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (as_of, h)
);

CREATE INDEX IF NOT EXISTS ix_spx_density_forecast_asof
  ON uw_scan.spx_density_forecast (as_of DESC);

COMMENT ON TABLE uw_scan.spx_density_forecast IS
  'DISPLAY-ONLY research surface (signal-lab v13 PASS): 1-5 trading-day SPX conditional '
  'density cone + prospective shadow log. origin=reconstructed rows are in-sample backfill '
  'and are tallied separately. Never a trading input.';
