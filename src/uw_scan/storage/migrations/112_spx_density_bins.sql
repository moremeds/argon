-- 112_spx_density_bins.sql — per-horizon simulated density histogram for the SPX cone.
--
-- The cone job already simulates M=10,000 paths and `Cone.samples` keeps them; until now
-- only the 7 quantiles survived to storage. The focused (next-session) chart view needs the
-- SHAPE of the distribution, and reconstructing a density from 7 knots is an interpolation
-- artefact, not the model's output. This column stores the histogram taken from the same
-- draws the quantiles come from.
--
-- Purely additive read-out: nothing here feeds the quantile math, so the v13 parity gate is
-- unaffected. Nullable — rows issued before this migration keep NULL and the chart falls
-- back to the quantile bands.
-- Idempotent.

SET search_path TO uw_scan, public;

ALTER TABLE uw_scan.spx_density_forecast
  ADD COLUMN IF NOT EXISTS density_bins_jsonb JSONB;

COMMENT ON COLUMN uw_scan.spx_density_forecast.density_bins_jsonb IS
  'Histogram of the Monte-Carlo draws for this horizon, in cumulative simple-return units '
  '(same units as q05..q95): {lo, hi, n_bins, counts[], total, clipped}. Bin i spans '
  '[lo + i*(hi-lo)/n_bins, lo + (i+1)*(hi-lo)/n_bins). Range is clipped to the 0.5th-99.5th '
  'percentile so a single outlier path cannot squash the body; `clipped` counts the draws '
  'outside it. NULL for rows issued before migration 112.';
