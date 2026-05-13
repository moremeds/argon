-- Prevent duplicate active local Codex analyses for the same deterministic
-- prompt input while still allowing explicit reruns after a prior terminal row.

SET search_path TO uw_scan, public;

WITH ranked_active AS (
    SELECT
        analysis_id,
        row_number() OVER (
            PARTITION BY ticker, analysis_input_hash, prompt_version, model
            ORDER BY
                CASE status WHEN 'running' THEN 0 ELSE 1 END,
                started_at DESC NULLS LAST,
                requested_at DESC
        ) AS duplicate_rank
    FROM uw_scan.trade_insight_ai_analyses
    WHERE status IN ('queued', 'running')
)
UPDATE uw_scan.trade_insight_ai_analyses AS analysis
SET
    status = 'failed',
    error_message = 'Superseded by duplicate active analysis during migration',
    finished_at = now()
FROM ranked_active
WHERE analysis.analysis_id = ranked_active.analysis_id
  AND ranked_active.duplicate_rank > 1;

CREATE UNIQUE INDEX IF NOT EXISTS idx_trade_insight_ai_analyses_active_reuse
    ON uw_scan.trade_insight_ai_analyses (
        ticker,
        analysis_input_hash,
        prompt_version,
        model
    )
    WHERE status IN ('queued', 'running');
