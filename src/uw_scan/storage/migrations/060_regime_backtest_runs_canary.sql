-- src/uw_scan/storage/migrations/060_regime_backtest_runs_canary.sql
-- v0.4 patch C5: widen the CHECK constraint on
-- uw_scan.regime_backtest_runs to include the new 'canary' indicator.
-- See docs/superpowers/specs/2026-05-26-5pct-canary-indicator-design.md §8.

SET search_path TO uw_scan, public;
BEGIN;

ALTER TABLE uw_scan.regime_backtest_runs
    DROP CONSTRAINT IF EXISTS regime_backtest_runs_indicator_check;
ALTER TABLE uw_scan.regime_backtest_runs
    ADD CONSTRAINT regime_backtest_runs_indicator_check
    CHECK (indicator IN ('cri', 'vcg', 'canary'));

COMMIT;
