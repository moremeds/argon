-- 059_regime_backtest_research_scope.sql
-- Promote run_scope, composite_method, credit_proxy out of summary['extras']
-- so the API can structurally exclude research rows from production queries.
-- Two-phase to preserve historical research labels in existing rows.
--
-- Idempotent via IF NOT EXISTS + DO blocks (Postgres has no
-- ADD CONSTRAINT IF NOT EXISTS).

SET search_path TO uw_scan, public;

BEGIN;

-- Phase 1: add columns nullable
ALTER TABLE uw_scan.regime_backtest_runs
  ADD COLUMN IF NOT EXISTS run_scope TEXT,
  ADD COLUMN IF NOT EXISTS composite_method TEXT,
  ADD COLUMN IF NOT EXISTS credit_proxy TEXT;

-- Phase 2: backfill from summary['extras'] (heuristics ordered most-specific first)
UPDATE uw_scan.regime_backtest_runs
SET credit_proxy = summary->'extras'->>'credit_proxy'
WHERE credit_proxy IS NULL
  AND summary->'extras' ? 'credit_proxy';

-- Phase 2b: VCG rows without an extras.credit_proxy key default to HYG —
-- the production-canonical proxy. NULL would later fail
-- regime_backtest_runs_vcg_credit_proxy_check.
UPDATE uw_scan.regime_backtest_runs
SET credit_proxy = 'HYG'
WHERE credit_proxy IS NULL AND indicator = 'vcg';

UPDATE uw_scan.regime_backtest_runs
SET composite_method = COALESCE(summary->'extras'->>'composite_method', 'single_proxy')
WHERE composite_method IS NULL;

UPDATE uw_scan.regime_backtest_runs
SET run_scope = CASE
  -- Explicit scope marker takes precedence over every other heuristic
  WHEN summary->'extras'->>'run_scope' IN ('production', 'research')
    THEN summary->'extras'->>'run_scope'
  -- composite_version is the most reliable research indicator. Check this
  -- BEFORE proxy/method backfilled defaults can mask the truth — a row with
  -- composite_version LIKE '%candidate%' is research even if its summary
  -- lacks extras.credit_proxy/extras.composite_method (which would otherwise
  -- get backfilled to 'HYG'/'single_proxy' and silently flip it to production
  -- in the next two branches).
  WHEN composite_version LIKE '%candidate%' THEN 'research'
  WHEN COALESCE(summary->'extras'->>'credit_proxy', credit_proxy) LIKE 'COMPOSITE%'
    THEN 'research'
  WHEN COALESCE(summary->'extras'->>'composite_method', composite_method) <> 'single_proxy'
    AND COALESCE(summary->'extras'->>'composite_method', composite_method) IS NOT NULL
    THEN 'research'
  ELSE 'production'
END
WHERE run_scope IS NULL;

-- Phase 3: set defaults (post-backfill so they don't overwrite historical labels)
ALTER TABLE uw_scan.regime_backtest_runs
  ALTER COLUMN run_scope SET DEFAULT 'production',
  ALTER COLUMN composite_method SET DEFAULT 'single_proxy';

-- Phase 4: NOT NULL
ALTER TABLE uw_scan.regime_backtest_runs
  ALTER COLUMN run_scope SET NOT NULL,
  ALTER COLUMN composite_method SET NOT NULL;

-- Phase 5: CHECK constraints (DO blocks because Postgres has no
-- ADD CONSTRAINT IF NOT EXISTS).
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conname = 'regime_backtest_runs_scope_check'
      AND conrelid = 'uw_scan.regime_backtest_runs'::regclass
  ) THEN
    ALTER TABLE uw_scan.regime_backtest_runs
      ADD CONSTRAINT regime_backtest_runs_scope_check
      CHECK (run_scope IN ('production', 'research'));
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conname = 'regime_backtest_runs_composite_method_check'
      AND conrelid = 'uw_scan.regime_backtest_runs'::regclass
  ) THEN
    ALTER TABLE uw_scan.regime_backtest_runs
      ADD CONSTRAINT regime_backtest_runs_composite_method_check
      CHECK (composite_method IN (
        'single_proxy',
        'risk_parity_3',
        'risk_parity_hyjk',
        'hy_minus_ig_spread',
        'equal_weight_3'
      ));
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conname = 'regime_backtest_runs_vcg_credit_proxy_check'
      AND conrelid = 'uw_scan.regime_backtest_runs'::regclass
  ) THEN
    ALTER TABLE uw_scan.regime_backtest_runs
      ADD CONSTRAINT regime_backtest_runs_vcg_credit_proxy_check
      CHECK (indicator <> 'vcg' OR credit_proxy IS NOT NULL);
  END IF;
END $$;

-- Phase 6: index
CREATE INDEX IF NOT EXISTS idx_regime_runs_scope_indicator_version_proxy
  ON uw_scan.regime_backtest_runs
     (run_scope, indicator, composite_version, credit_proxy, composite_method, created_at DESC);

COMMIT;
