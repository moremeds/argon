-- 062_classification_unique_index.sql
-- Partial unique index preventing concurrent classification_accuracy runs from
-- creating duplicate completed rows for the same (vcg_source_run_id, label_version).
-- v0.3 / CR-2: closes the find-then-insert race in score_vcg_classification_accuracy.

SET search_path = uw_scan, public;

BEGIN;

CREATE UNIQUE INDEX IF NOT EXISTS regime_classification_completed_uniq
  ON uw_scan.regime_backtest_runs (
    indicator,
    composite_method,
    run_scope,
    ((params->>'vcg_source_run_id')::int),
    ((params->>'label_version')::int)
  )
  WHERE composite_method = 'classification_accuracy'
    AND completed_at IS NOT NULL
    AND archived_at IS NULL;

COMMIT;
