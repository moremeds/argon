-- 067_trade_insight_analysis_kind.sql
-- Add an explicit lane discriminator to trade_insight_ai_analyses so the
-- production "insights" card (prompt v5.3) and the new "blast" Trade Plan
-- lane (prompt trade-blast-v1) can be read independently.
--
-- NOTE: lane separation is ALREADY enforced by prompt_version, which is part
-- of both reuse unique indexes (idx_..._succeeded_reuse / idx_..._active_reuse)
-- and the enqueue ON CONFLICT target. prompt_version differs per lane
-- ('trade-insights-ai-v5.3' vs 'trade-blast-v1'), so cross-lane collisions
-- cannot occur. This column makes the lane explicit for reads/queries and
-- future-proofs against a prompt_version bump within a single lane. It is
-- intentionally NOT folded into the partial unique indexes to avoid fragile
-- partial-index ON CONFLICT predicate changes.
SET search_path TO uw_scan, public;

ALTER TABLE uw_scan.trade_insight_ai_analyses
    ADD COLUMN IF NOT EXISTS analysis_kind text NOT NULL DEFAULT 'insights';

-- Backfill any pre-existing blast-version rows (idempotent; none expected yet).
UPDATE uw_scan.trade_insight_ai_analyses
    SET analysis_kind = 'blast'
    WHERE prompt_version LIKE 'trade-blast%'
      AND analysis_kind <> 'blast';

-- Helps the lane-scoped reads (find_latest / count_queued filter by kind).
CREATE INDEX IF NOT EXISTS idx_trade_insight_ai_analyses_kind
    ON uw_scan.trade_insight_ai_analyses (ticker, analysis_kind, provider);
