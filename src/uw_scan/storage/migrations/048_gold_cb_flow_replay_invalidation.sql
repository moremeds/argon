-- 048_gold_cb_flow_replay_invalidation.sql — invalidate CB level-sum posture rows.
-- A short-lived bug summed CB reserve levels as a 12m flow after WGC data was
-- populated. Keep audit rows, but make replay prefer rows recomputed from
-- country-level net changes.

SET search_path TO uw_scan, public;

UPDATE uw_scan.gold_posture_daily
SET row_status = 'invalidated',
    superseded_reason = COALESCE(
      superseded_reason,
      'cb 12m flow fields contained summed reserve levels instead of net changes'
    )
WHERE row_status = 'active'
  AND (
    abs(COALESCE(cb_strategic_12m_sum_t, 0)) > 10000
    OR abs(COALESCE(cb_tactical_12m_sum_t, 0)) > 10000
    OR abs(COALESCE(cb_diversifier_12m_sum_t, 0)) > 10000
  );

WITH first_cb_populated AS (
  SELECT obs_date, min(computed_at) AS first_cb_computed_at
  FROM uw_scan.gold_posture_daily
  WHERE row_status = 'active'
    AND (
      cb_strategic_12m_sum_t IS NOT NULL
      OR cb_tactical_12m_sum_t IS NOT NULL
      OR cb_diversifier_12m_sum_t IS NOT NULL
    )
    AND abs(COALESCE(cb_strategic_12m_sum_t, 0)) <= 10000
    AND abs(COALESCE(cb_tactical_12m_sum_t, 0)) <= 10000
    AND abs(COALESCE(cb_diversifier_12m_sum_t, 0)) <= 10000
  GROUP BY obs_date
)
UPDATE uw_scan.gold_posture_daily p
SET row_status = 'invalidated',
    superseded_reason = COALESCE(
      p.superseded_reason,
      'superseded by later posture row populated with CB reserve flows'
    )
FROM first_cb_populated valid
WHERE p.row_status = 'active'
  AND p.obs_date = valid.obs_date
  AND p.computed_at < valid.first_cb_computed_at;
