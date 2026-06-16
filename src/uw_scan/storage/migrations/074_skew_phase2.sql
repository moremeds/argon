-- 074_skew_phase2.sql — Phase-2 increment-1.
-- skew_rv_reversion_verdicts: per (asset_class, deviation_class, tail) conclusion of
-- whether the 25d RR mean-reverts (descriptive RV axis, distinct from the directional
-- skew_directional_verdicts). Gated by a time-ordered walk-forward holdout AND a
-- per-calendar-quarter catastrophic-degradation gate on the RR history (the only OOS
-- test the ~1yr RR data supports). NO spread-P&L / net-of-cost. Idempotent.

SET search_path TO uw_scan, public;

CREATE TABLE IF NOT EXISTS uw_scan.skew_rv_reversion_verdicts (
  asset_class          TEXT NOT NULL,     -- index_macro | sector_etf | credit | single_name
  deviation_class      TEXT NOT NULL,     -- RICH | CHEAP | NORMAL
  tail                 TEXT NOT NULL,     -- put_skew | call_skew | flat
  verdict              TEXT NOT NULL,     -- REVERTS | NONE
  mean_drr             NUMERIC,           -- mean forward ΔRR (T+20) over the full sample
  mean_drr_holdout     NUMERIC,           -- mean forward ΔRR over the time-ordered holdout
  n                    INTEGER,
  n_holdout            INTEGER,
  survives_walkforward BOOLEAN,           -- holdout preserves the full-sample sign + magnitude
  survives_window_gate BOOLEAN,           -- no calendar quarter reverses the aggregate with larger magnitude
  as_of                DATE,
  inserted_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (asset_class, deviation_class, tail)
);

COMMENT ON TABLE uw_scan.skew_rv_reversion_verdicts
  IS 'Per-bucket RR mean-reversion conclusion (descriptive RV axis). REVERTS requires expected sign (CHEAP->+, RICH->-), |mean| over threshold, n over min, a time-ordered walk-forward holdout that preserves sign+magnitude, AND a per-calendar-quarter catastrophic-degradation gate (no sub-window reverses the aggregate with larger magnitude). In-sample over a single ~1yr window; NOT a P&L claim.';
