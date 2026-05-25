-- 057_regime_backtest_results.sql
-- Persists CRI + VCG backtest runs to Postgres.
--
-- Idempotent for clean re-application: re-running this file against a DB
-- that already has both tables (created by THIS migration) is a no-op.
--
-- NOT idempotent for partial-table repair: if a parallel/abandoned branch
-- created a partial version of either table without the constraints below,
-- this migration may fail (the CREATE TABLE IF NOT EXISTS skips the create,
-- but downstream INSERTs that reference window_days/completed_at will reject).
-- Recovery procedure (documented in the closure design spec §15 risk 3):
--   DROP TABLE IF EXISTS uw_scan.regime_backtest_daily;
--   DROP TABLE IF EXISTS uw_scan.regime_backtest_runs;
--   \i src/uw_scan/storage/migrations/057_regime_backtest_results.sql

SET search_path TO uw_scan, public;

BEGIN;

CREATE TABLE IF NOT EXISTS uw_scan.regime_backtest_runs (
  id                BIGSERIAL PRIMARY KEY,
  indicator         TEXT NOT NULL CHECK (indicator IN ('cri','vcg')),
  composite_version TEXT NOT NULL,
  start_date        DATE NOT NULL,
  end_date          DATE NOT NULL,
  window_days       INT  NOT NULL,  -- rolling lookback in trading days; `window` is a PG reserved keyword, hence the suffix
  n_days            INT  NOT NULL,
  params            JSONB NOT NULL DEFAULT '{}'::jsonb,
  summary           JSONB NOT NULL DEFAULT '{}'::jsonb,
  note              TEXT,
  created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  completed_at      TIMESTAMPTZ,   -- NULL until bulk_insert_daily finishes; set as final step. find_latest_run filters on this.
  CONSTRAINT regime_backtest_runs_date_range  CHECK (start_date <= end_date),
  CONSTRAINT regime_backtest_runs_n_days_nonneg CHECK (n_days >= 0),
  CONSTRAINT regime_backtest_runs_window_pos    CHECK (window_days > 0)
);

CREATE INDEX IF NOT EXISTS idx_regime_backtest_runs_completed
  ON uw_scan.regime_backtest_runs (indicator, completed_at DESC) WHERE completed_at IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_regime_backtest_runs_lookup
  ON uw_scan.regime_backtest_runs (indicator, composite_version, created_at DESC);

CREATE TABLE IF NOT EXISTS uw_scan.regime_backtest_daily (
  run_id     BIGINT NOT NULL REFERENCES uw_scan.regime_backtest_runs(id) ON DELETE CASCADE,
  trade_date DATE   NOT NULL,
  score      NUMERIC NOT NULL,
  level      TEXT,
  payload    JSONB  NOT NULL DEFAULT '{}'::jsonb,
  PRIMARY KEY (run_id, trade_date)
);

CREATE INDEX IF NOT EXISTS idx_regime_backtest_daily_date
  ON uw_scan.regime_backtest_daily (trade_date, run_id);

COMMIT;
