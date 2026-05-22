-- 053_trade_insights_ai_provider_column.sql
-- Add provider column + extend cache-reuse indexes for the Claude provider.
-- Existing rows backfill with 'codex' (the only path that existed before this
-- migration). Per-provider cache reuse is enforced by the new index keys.

SET search_path TO uw_scan, public;

ALTER TABLE uw_scan.trade_insight_ai_analyses
    ADD COLUMN IF NOT EXISTS provider TEXT NOT NULL DEFAULT 'codex';

ALTER TABLE uw_scan.trade_insight_ai_analyses
    DROP CONSTRAINT IF EXISTS trade_insight_ai_analyses_provider_check;

ALTER TABLE uw_scan.trade_insight_ai_analyses
    ADD CONSTRAINT trade_insight_ai_analyses_provider_check
        CHECK (provider IN ('codex', 'claude'));

DROP INDEX IF EXISTS uw_scan.idx_trade_insight_ai_analyses_succeeded_reuse;
CREATE UNIQUE INDEX IF NOT EXISTS idx_trade_insight_ai_analyses_succeeded_reuse
    ON uw_scan.trade_insight_ai_analyses (
        ticker, analysis_input_hash, prompt_version, model, provider
    )
    WHERE status = 'succeeded';

DROP INDEX IF EXISTS uw_scan.idx_trade_insight_ai_analyses_active_reuse;
CREATE UNIQUE INDEX IF NOT EXISTS idx_trade_insight_ai_analyses_active_reuse
    ON uw_scan.trade_insight_ai_analyses (
        ticker, analysis_input_hash, prompt_version, model, provider
    )
    WHERE status IN ('queued', 'running');

CREATE INDEX IF NOT EXISTS idx_trade_insight_ai_analyses_provider_queue
    ON uw_scan.trade_insight_ai_analyses (provider, status, requested_at);

COMMENT ON COLUMN uw_scan.trade_insight_ai_analyses.provider IS
    'AI provider that produced this analysis: codex or claude. '
    'Each Run enqueues one row per enabled provider; per-provider cache reuse '
    'is enforced by indexes keyed on (ticker, analysis_input_hash, '
    'prompt_version, model, provider).';
