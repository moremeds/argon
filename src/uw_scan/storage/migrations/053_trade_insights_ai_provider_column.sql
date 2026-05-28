-- 053_trade_insights_ai_provider_column.sql
-- Add provider column + extend cache-reuse indexes for the Claude provider.
-- Existing rows backfill with 'codex' (the only path that existed before this
-- migration). Per-provider cache reuse is enforced by the new index keys.

SET search_path TO uw_scan, public;

ALTER TABLE uw_scan.trade_insight_ai_analyses
    ADD COLUMN IF NOT EXISTS provider TEXT NOT NULL DEFAULT 'codex';

-- Idempotent CHECK install. Two-condition guard:
--   1. Constraint is missing (don't replace a wider one already in force).
--   2. No existing rows would violate the narrow value set.
-- A later migration (063) widens the value set to include 'deepseek'. If
-- this migration unconditionally added the narrow constraint on replay it
-- would fail with "violated by some row" once deepseek rows exist — and if
-- it had previously dropped the wide constraint, the narrow ADD would still
-- fail on rows the wide constraint had legitimately permitted. By skipping
-- the ADD whenever it would fail, the migration becomes safe to replay from
-- any post-063 state; 063 itself then re-establishes the wide constraint.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'trade_insight_ai_analyses_provider_check'
          AND conrelid = 'uw_scan.trade_insight_ai_analyses'::regclass
    ) AND NOT EXISTS (
        SELECT 1 FROM uw_scan.trade_insight_ai_analyses
        WHERE provider NOT IN ('codex', 'claude')
    ) THEN
        ALTER TABLE uw_scan.trade_insight_ai_analyses
            ADD CONSTRAINT trade_insight_ai_analyses_provider_check
                CHECK (provider IN ('codex', 'claude'));
    END IF;
END $$;

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
