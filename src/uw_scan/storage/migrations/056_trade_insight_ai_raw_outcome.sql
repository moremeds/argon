-- 056_trade_insight_ai_raw_outcome.sql — idempotent.
-- Add raw_outcome_jsonb to trade_insight_ai_analyses so that when a runner
-- returns a parseable JSON object but the downstream validator rejects it
-- (e.g., the no-whitewashing rule firing on status_observed drift), we
-- preserve the rejected payload for diagnosis.
--
-- Until now, validation failure paths discarded the runner output entirely,
-- leaving only the 1-line error message. That made every Codex / Claude
-- validation failure undiagnosable without re-running.
--
-- This column is NULL for:
--   * rows that succeeded (outcome lives in outcome_jsonb)
--   * rows that failed BEFORE the runner returned (subprocess crash, timeout,
--     non-JSON output, prompt-prep error)
-- and POPULATED for:
--   * rows where the runner returned a JSON object that subsequently failed
--     validation (validator rejection, post-parse normalization failure)

SET search_path TO uw_scan, public;

ALTER TABLE uw_scan.trade_insight_ai_analyses
    ADD COLUMN IF NOT EXISTS raw_outcome_jsonb jsonb;
