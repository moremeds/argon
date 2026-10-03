-- 047_gold_posture_row_status.sql — Gold replay invalidation.
-- Keeps posture audit rows while letting normal replay skip rows later found to
-- contain bad persisted payloads.

SET search_path TO uw_scan, public;

ALTER TABLE uw_scan.gold_posture_daily
  ADD COLUMN IF NOT EXISTS row_status TEXT NOT NULL DEFAULT 'active',
  ADD COLUMN IF NOT EXISTS superseded_reason TEXT NULL;

CREATE INDEX IF NOT EXISTS idx_gold_posture_daily_replay_active
  ON uw_scan.gold_posture_daily (obs_date, computed_at ASC)
  WHERE row_status = 'active';

-- REPLAYED DML REMOVED (2026-10-03). Three UPDATEs here used to invalidate
-- posture rows (ounce-scaled gld_history_jsonb; rows earlier than the first valid
-- GLD history that day; rows dated after the latest GLD_CLOSE). The API
-- self-migrates on every boot, so they re-ran on every deploy against rows written
-- later, which changed which row fetch_gold_posture_as_of (computed_at ASC)
-- returns. The 'after latest GLD close' predicate fired on deploys through
-- 2026-08-16 (6 rows). The one-time effect was already applied: on prod
-- 2026-10-03 all three predicates matched 0 rows. A fresh install has no rows.
-- Data DML in a migration must be insert-only -- enforced by
-- tests/unit/storage/test_migration_dml_allowlist.py.
