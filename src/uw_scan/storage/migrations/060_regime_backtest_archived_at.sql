-- 060_regime_backtest_archived_at.sql
-- Phase A1: soft-delete column on regime_backtest_runs.
--
-- Smoke runs produced during development (especially classification baselines)
-- need to be archived without DELETE so the audit trail stays intact. The
-- partial unique index in Migration 062 also relies on `archived_at IS NULL`
-- to scope uniqueness to live rows only.
--
-- Idempotent: IF NOT EXISTS guards the column and partial index.

SET search_path TO uw_scan, public;

BEGIN;

ALTER TABLE uw_scan.regime_backtest_runs
  ADD COLUMN IF NOT EXISTS archived_at TIMESTAMPTZ;

-- Live-row filter used by most query paths (find_latest_run, paginated lists,
-- the partial unique index in Migration 062). Indexing live rows only keeps
-- the index small and fast since archived rows are read-rare.
CREATE INDEX IF NOT EXISTS idx_regime_backtest_runs_live
  ON uw_scan.regime_backtest_runs (indicator, composite_version, created_at DESC)
  WHERE archived_at IS NULL;

COMMIT;
