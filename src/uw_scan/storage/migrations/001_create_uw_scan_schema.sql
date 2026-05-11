CREATE SCHEMA IF NOT EXISTS uw_scan;

CREATE TABLE IF NOT EXISTS uw_scan.schema_versions (
    version TEXT PRIMARY KEY,
    applied_at_utc TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS uw_scan.scan_runs (
    run_id TEXT PRIMARY KEY,
    mode TEXT NOT NULL,
    started_at_utc TIMESTAMPTZ NOT NULL,
    completed_at_utc TIMESTAMPTZ,
    status TEXT NOT NULL,
    request_budget INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS uw_scan.source_feeds (
    source_feed_id BIGSERIAL PRIMARY KEY,
    source_kind TEXT NOT NULL,
    source_label TEXT NOT NULL,
    source_url TEXT,
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    created_at_utc TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (source_kind, source_label, source_url)
);

CREATE TABLE IF NOT EXISTS uw_scan.source_imports (
    source_import_id BIGSERIAL PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES uw_scan.scan_runs(run_id),
    source_feed_id BIGINT NOT NULL REFERENCES uw_scan.source_feeds(source_feed_id),
    symbol_or_contract TEXT NOT NULL,
    import_status TEXT NOT NULL,
    parsed_at_utc TIMESTAMPTZ NOT NULL,
    error_message TEXT,
    UNIQUE (run_id, source_feed_id, symbol_or_contract)
);

CREATE TABLE IF NOT EXISTS uw_scan.raw_payloads (
    raw_payload_id BIGSERIAL PRIMARY KEY,
    payload_compressed BYTEA NOT NULL,
    content_encoding TEXT NOT NULL DEFAULT 'gzip',
    content_sha256 TEXT NOT NULL,
    payload_size_bytes INTEGER NOT NULL,
    created_at_utc TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS uw_scan.api_request_audit (
    api_request_id BIGSERIAL PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES uw_scan.scan_runs(run_id),
    request_fingerprint TEXT NOT NULL,
    endpoint TEXT NOT NULL,
    normalized_params TEXT NOT NULL,
    response_status INTEGER,
    latency_ms INTEGER,
    fetched_at_utc TIMESTAMPTZ NOT NULL,
    raw_payload_id BIGINT REFERENCES uw_scan.raw_payloads(raw_payload_id),
    error_message TEXT,
    UNIQUE (run_id, request_fingerprint)
);

CREATE TABLE IF NOT EXISTS uw_scan.option_contract_snapshots (
    option_contract_snapshot_id BIGSERIAL PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES uw_scan.scan_runs(run_id),
    option_symbol TEXT NOT NULL,
    ticker TEXT NOT NULL,
    market_date DATE NOT NULL,
    fetched_at_utc TIMESTAMPTZ NOT NULL,
    expiry DATE NOT NULL,
    strike NUMERIC NOT NULL,
    option_type TEXT NOT NULL,
    implied_volatility NUMERIC,
    open_interest INTEGER,
    previous_open_interest INTEGER,
    volume INTEGER,
    premium NUMERIC,
    bid NUMERIC,
    ask NUMERIC,
    mid NUMERIC,
    ask_volume INTEGER,
    bid_volume INTEGER,
    multi_leg_volume INTEGER,
    sweep_volume INTEGER,
    UNIQUE (run_id, option_symbol, fetched_at_utc)
);

CREATE TABLE IF NOT EXISTS uw_scan.greeks_by_expiry_strike (
    greek_row_id BIGSERIAL PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES uw_scan.scan_runs(run_id),
    ticker TEXT NOT NULL,
    market_date DATE NOT NULL,
    fetched_at_utc TIMESTAMPTZ NOT NULL,
    expiry DATE NOT NULL,
    strike NUMERIC NOT NULL,
    call_iv NUMERIC,
    put_iv NUMERIC,
    delta NUMERIC,
    gamma NUMERIC,
    theta NUMERIC,
    vega NUMERIC,
    rho NUMERIC,
    vanna NUMERIC,
    charm NUMERIC,
    UNIQUE (run_id, ticker, market_date, expiry, strike)
);

CREATE TABLE IF NOT EXISTS uw_scan.oi_by_expiry (
    oi_by_expiry_id BIGSERIAL PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES uw_scan.scan_runs(run_id),
    ticker TEXT NOT NULL,
    market_date DATE NOT NULL,
    fetched_at_utc TIMESTAMPTZ NOT NULL,
    expiry DATE NOT NULL,
    call_open_interest INTEGER,
    put_open_interest INTEGER,
    UNIQUE (run_id, ticker, market_date, expiry)
);

CREATE TABLE IF NOT EXISTS uw_scan.opportunity_scores (
    opportunity_score_id BIGSERIAL PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES uw_scan.scan_runs(run_id),
    ticker TEXT NOT NULL,
    option_symbol TEXT,
    score INTEGER NOT NULL,
    direction TEXT NOT NULL,
    setup_types TEXT NOT NULL,
    confirmations TEXT NOT NULL,
    warnings TEXT NOT NULL,
    created_at_utc TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_uw_scan_contract_ticker_expiry
    ON uw_scan.option_contract_snapshots (ticker, expiry, strike);

CREATE INDEX IF NOT EXISTS idx_uw_scan_greeks_ticker_expiry
    ON uw_scan.greeks_by_expiry_strike (ticker, expiry, strike);

INSERT INTO uw_scan.schema_versions (version)
VALUES ('001_create_uw_scan_schema')
ON CONFLICT (version) DO NOTHING;
