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

UPDATE uw_scan.gold_posture_daily
SET row_status = 'invalidated',
    superseded_reason = COALESCE(
      superseded_reason,
      'gld_history_jsonb stored ounces before tonnes normalization'
    )
WHERE row_status = 'active'
  AND gld_history_jsonb IS NOT NULL
  AND EXISTS (
    SELECT 1
    FROM jsonb_array_elements(gld_history_jsonb) AS elem
    WHERE (elem ->> 'value')::numeric > 10000
  );

WITH first_valid_gld_history AS (
  SELECT p.obs_date, min(p.computed_at) AS first_valid_computed_at
  FROM uw_scan.gold_posture_daily p
  WHERE p.gld_history_jsonb IS NOT NULL
    AND jsonb_array_length(p.gld_history_jsonb) > 0
    AND NOT EXISTS (
      SELECT 1
      FROM jsonb_array_elements(p.gld_history_jsonb) AS elem
      WHERE (elem ->> 'value')::numeric > 10000
    )
  GROUP BY p.obs_date
)
UPDATE uw_scan.gold_posture_daily p
SET row_status = 'invalidated',
    superseded_reason = COALESCE(
      p.superseded_reason,
      'superseded by later posture row with valid GLD history payload'
    )
FROM first_valid_gld_history valid
WHERE p.row_status = 'active'
  AND p.obs_date = valid.obs_date
  AND p.computed_at < valid.first_valid_computed_at;

WITH latest_gld_close AS (
  SELECT max(obs_date) AS obs_date
  FROM uw_scan.macro_series_daily
  WHERE series_id = 'GLD_CLOSE'
)
UPDATE uw_scan.gold_posture_daily p
SET row_status = 'invalidated',
    superseded_reason = COALESCE(
      p.superseded_reason,
      'posture obs_date is after latest available GLD close'
    )
FROM latest_gld_close latest
WHERE p.row_status = 'active'
  AND latest.obs_date IS NOT NULL
  AND p.obs_date > latest.obs_date;
