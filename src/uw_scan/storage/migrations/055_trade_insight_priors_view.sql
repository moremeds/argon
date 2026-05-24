-- 055_trade_insight_priors_view.sql — idempotent.
-- Aggregates trade_insight_outcomes into per-provider per-archetype
-- hit-rate stats. View (not materialized) — recomputed on each query,
-- which is fine while sample sizes are small (~hundreds of rows).
-- Promote to a materialized view + REFRESH from the nightly worker
-- when row count crosses the slow-query threshold.
--
-- Archetype + bias + entry_state are extracted from the source
-- trade_insight_ai_analyses.outcome_jsonb headline — they're not
-- denormalized onto trade_insight_outcomes, because reading the JSON
-- key on demand keeps the ledger schema independent of prompt-version
-- field renames (a v5.4 that reshapes headline can still aggregate
-- via this view by updating only the JSON path here).

SET search_path TO uw_scan, public;

CREATE OR REPLACE VIEW uw_scan.trade_insight_provider_archetype_priors AS
SELECT
    o.provider,
    o.prompt_version,
    a.outcome_jsonb->'headline'->>'thesis_archetype'   AS thesis_archetype,
    a.outcome_jsonb->'headline'->>'directional_bias'   AS directional_bias,
    a.outcome_jsonb->'headline'->>'entry_state'        AS entry_state,
    count(*)                                            AS sample_count,
    count(*) FILTER (WHERE o.resolved_outcome = 'target_hit')        AS target_hit_count,
    count(*) FILTER (WHERE o.resolved_outcome = 'invalidation_hit')  AS invalidation_hit_count,
    count(*) FILTER (WHERE o.resolved_outcome = 'pending')           AS pending_count,
    count(*) FILTER (WHERE o.resolved_outcome = 'expired_no_resolution') AS expired_no_resolution_count,
    -- Hit rate among RESOLVED outcomes (excludes pending/expired so a
    -- mostly-pending cohort doesn't look like a 0% hit rate).
    ROUND(
        (count(*) FILTER (WHERE o.resolved_outcome = 'target_hit'))::numeric
        / NULLIF(
            count(*) FILTER (WHERE o.resolved_outcome IN ('target_hit','invalidation_hit')),
            0
          )
        * 100,
        2
    ) AS hit_rate_pct,
    -- Median days to resolution among rows that resolved. NULL when
    -- the cohort has zero resolved outcomes.
    PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY o.days_to_resolution)
        FILTER (WHERE o.days_to_resolution IS NOT NULL) AS median_days_to_resolution
FROM uw_scan.trade_insight_outcomes o
JOIN uw_scan.trade_insight_ai_analyses a USING (analysis_id)
WHERE a.outcome_jsonb IS NOT NULL
GROUP BY
    o.provider,
    o.prompt_version,
    a.outcome_jsonb->'headline'->>'thesis_archetype',
    a.outcome_jsonb->'headline'->>'directional_bias',
    a.outcome_jsonb->'headline'->>'entry_state';

COMMENT ON VIEW uw_scan.trade_insight_provider_archetype_priors IS
    'Per-provider per-archetype hit-rate priors. Sample_count includes '
    'all outcomes for the cohort; hit_rate_pct is computed over RESOLVED '
    'outcomes only (excludes pending/expired). Surfaced by '
    '/api/trade-insights/priors.';
