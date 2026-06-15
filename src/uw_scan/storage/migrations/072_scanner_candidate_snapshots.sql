-- 072_scanner_candidate_snapshots.sql — markout-ready candidate snapshots for
-- BOTH scanner sections (watchlist + discovery). One row per candidate
-- emission. Idempotent.

SET search_path TO uw_scan, public;

CREATE TABLE IF NOT EXISTS uw_scan.scanner_candidate_snapshots (
  id              BIGSERIAL PRIMARY KEY,
  run_id          BIGINT,
  section         TEXT NOT NULL,            -- 'watchlist' | 'discovery'
  ticker          TEXT NOT NULL,
  scored_at       TIMESTAMPTZ NOT NULL,
  bias            TEXT,                     -- 'bullish'|'bearish'|'mixed'|'neutral'
  direction       TEXT,                     -- 'long'|'short'|NULL  (markout sign)
  score           NUMERIC(8,3),
  score_model     TEXT NOT NULL,            -- 'edge_quality_v1' | 'watchlist_tier_v1'
  score_breakdown JSONB,
  spot_at_signal  NUMERIC,
  is_type_f       BOOLEAN,                  -- watchlist multi-signal flag (NULL for discovery)
  evidence        JSONB,                    -- per-factor metadata
  inserted_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_scs_ticker_scored
  ON uw_scan.scanner_candidate_snapshots (ticker, scored_at DESC);
CREATE INDEX IF NOT EXISTS ix_scs_section_scored
  ON uw_scan.scanner_candidate_snapshots (section, scored_at DESC);
CREATE INDEX IF NOT EXISTS ix_scs_run
  ON uw_scan.scanner_candidate_snapshots (run_id);
