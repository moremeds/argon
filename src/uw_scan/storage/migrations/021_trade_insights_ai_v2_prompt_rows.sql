-- Keep active Trade Insights AI rows aligned with the v2 prompt contract.
-- Old active rows were created with a v1 prompt version and can otherwise be
-- claimed by a newer worker, producing schema_version mismatch failures.

SET search_path TO uw_scan, public;

UPDATE uw_scan.trade_insight_ai_analyses
SET
    status = 'failed',
    error_message = 'Superseded by trade-insights-ai-v2 prompt version',
    finished_at = COALESCE(finished_at, now())
WHERE prompt_version <> 'trade-insights-ai-v2'
  AND status IN ('queued', 'running');

UPDATE uw_scan.trade_insight_ai_analyses
SET analysis_input_jsonb = jsonb_set(
    analysis_input_jsonb,
    '{prompt_version}',
    '"trade-insights-ai-v2"'::jsonb,
    true
)
WHERE prompt_version = 'trade-insights-ai-v2'
  AND COALESCE(analysis_input_jsonb->>'prompt_version', '') <> 'trade-insights-ai-v2';
