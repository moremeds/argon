-- Persist operator-triggered local Codex analyses separately from deterministic
-- Trade Insights snapshots. AI output is audit/commentary only and must never
-- mutate deterministic candidate rows.

SET search_path TO uw_scan, public;

CREATE TABLE IF NOT EXISTS uw_scan.trade_insight_ai_analyses (
    analysis_id                 UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    snapshot_id                 BIGINT NOT NULL REFERENCES uw_scan.trade_insight_snapshots(snapshot_id) ON DELETE CASCADE,
    ticker                      TEXT NOT NULL,
    run_id                      BIGINT NOT NULL,
    trade_insights_input_hash   TEXT NOT NULL,
    analysis_input_hash         TEXT NOT NULL,
    analysis_input_jsonb        JSONB NOT NULL,
    model                       TEXT NOT NULL,
    prompt_version              TEXT NOT NULL,
    prompt_text                 TEXT,
    prompt_payload_jsonb        JSONB,
    output_schema_jsonb         JSONB,
    status                      TEXT NOT NULL DEFAULT 'queued',
    outcome_jsonb               JSONB,
    markdown                    TEXT,
    error_message               TEXT,
    requested_at                TIMESTAMPTZ NOT NULL DEFAULT now(),
    started_at                  TIMESTAMPTZ,
    produced_at                 TIMESTAMPTZ,
    finished_at                 TIMESTAMPTZ,
    CONSTRAINT trade_insight_ai_analyses_status_check
        CHECK (status IN ('queued', 'running', 'succeeded', 'failed'))
);

CREATE INDEX IF NOT EXISTS idx_trade_insight_ai_analyses_queue
    ON uw_scan.trade_insight_ai_analyses (status, requested_at);

CREATE UNIQUE INDEX IF NOT EXISTS idx_trade_insight_ai_analyses_succeeded_reuse
    ON uw_scan.trade_insight_ai_analyses (
        ticker,
        analysis_input_hash,
        prompt_version,
        model
    )
    WHERE status = 'succeeded';

CREATE INDEX IF NOT EXISTS idx_trade_insight_ai_analyses_ticker_requested
    ON uw_scan.trade_insight_ai_analyses (ticker, requested_at DESC);

COMMENT ON TABLE uw_scan.trade_insight_ai_analyses IS
    'Operator-triggered local Codex analyses over deterministic Trade Insights and tab payloads.';
