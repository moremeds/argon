-- 063_trade_insights_ai_deepseek_provider.sql
-- Widen the trade_insight_ai_analyses.provider CHECK constraint to admit
-- the deepseek provider added in this PR. Idempotent (DROP IF EXISTS
-- before ADD CONSTRAINT) so re-running migrate.sh is a no-op.

SET search_path TO uw_scan, public;

ALTER TABLE uw_scan.trade_insight_ai_analyses
    DROP CONSTRAINT IF EXISTS trade_insight_ai_analyses_provider_check;

ALTER TABLE uw_scan.trade_insight_ai_analyses
    ADD CONSTRAINT trade_insight_ai_analyses_provider_check
        CHECK (provider IN ('codex', 'claude', 'deepseek'));

COMMENT ON COLUMN uw_scan.trade_insight_ai_analyses.provider IS
    'AI provider that produced this analysis: codex, claude, or deepseek. '
    'Each Run enqueues one row per enabled provider; per-provider cache reuse '
    'is enforced by the unique indexes keyed on (ticker, analysis_input_hash, '
    'prompt_version, model, provider).';
