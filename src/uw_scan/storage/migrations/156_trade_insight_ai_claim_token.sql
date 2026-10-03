-- 156_trade_insight_ai_claim_token.sql — per-claim fencing token for the
-- Trade Insights AI queue (same pattern as 025_jobs_claim_token.sql).
--
-- The AI worker reclaims a 'running' row whose started_at is older than
-- timeout + 60 s. complete/fail used to update by analysis_id alone, so a
-- worker that overran past that window could overwrite the result of the
-- worker that reclaimed the row. Each claim now stamps a fresh claim_token,
-- and complete/fail match on it.
--
-- Idempotent: ADD COLUMN IF NOT EXISTS, nullable, no default (metadata-only
-- in PG 11+). No backfill: rows claimed before this column existed (or by an
-- old-version worker during a rollout) keep NULL, and only a worker that
-- itself claimed with a token fences on it.

SET search_path TO uw_scan, public;

CREATE EXTENSION IF NOT EXISTS "pgcrypto";

ALTER TABLE uw_scan.trade_insight_ai_analyses
  ADD COLUMN IF NOT EXISTS claim_token UUID;
