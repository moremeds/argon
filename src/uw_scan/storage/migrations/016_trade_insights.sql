-- Persist deterministic Trade Insights outputs for later validation/backtests.
-- The UI renders the current response, but research improvement depends on
-- retaining exactly what the rule engine emitted for each source run.

SET search_path TO uw_scan, public;

CREATE TABLE IF NOT EXISTS uw_scan.trade_insight_snapshots (
    snapshot_id                  BIGSERIAL PRIMARY KEY,
    run_id                       BIGINT NOT NULL REFERENCES uw_scan.scan_runs(run_id) ON DELETE CASCADE,
    ticker                       TEXT NOT NULL,
    as_of                        TIMESTAMPTZ,
    assembler_version            TEXT NOT NULL,
    input_hash                   TEXT NOT NULL,
    source_reconciliation_status TEXT,
    confidence_label             TEXT,
    data_quality_label           TEXT,
    preferred_idea_id            TEXT,
    payload_jsonb                JSONB NOT NULL,
    created_at                   TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (run_id, ticker, assembler_version, input_hash)
);

CREATE TABLE IF NOT EXISTS uw_scan.trade_insight_candidates (
    snapshot_id       BIGINT NOT NULL REFERENCES uw_scan.trade_insight_snapshots(snapshot_id) ON DELETE CASCADE,
    idea_id           TEXT NOT NULL,
    ticker            TEXT NOT NULL,
    run_id            BIGINT NOT NULL,
    structure         TEXT NOT NULL,
    expression_type   TEXT,
    rank              INTEGER NOT NULL,
    status            TEXT NOT NULL,
    net_credit_debit  NUMERIC,
    max_profit        NUMERIC,
    max_loss          NUMERIC,
    edge_source       TEXT,
    risk_flags        TEXT[] NOT NULL DEFAULT '{}',
    legs_jsonb        JSONB NOT NULL DEFAULT '[]'::jsonb,
    candidate_jsonb   JSONB NOT NULL,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (snapshot_id, idea_id)
);

CREATE INDEX IF NOT EXISTS idx_trade_insight_snapshots_ticker_created
    ON uw_scan.trade_insight_snapshots (ticker, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_trade_insight_candidates_structure_status
    ON uw_scan.trade_insight_candidates (structure, status, rank);

COMMENT ON TABLE uw_scan.trade_insight_snapshots IS
    'Idempotent deterministic Trade Insights response snapshots used for later validation and backtests.';
COMMENT ON TABLE uw_scan.trade_insight_candidates IS
    'Queryable candidate rows emitted by the deterministic Trade Insights assembler.';
