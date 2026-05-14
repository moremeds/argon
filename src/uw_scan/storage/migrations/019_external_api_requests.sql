SET search_path TO uw_scan, public;

CREATE TABLE IF NOT EXISTS uw_scan.external_api_requests (
    request_id BIGSERIAL PRIMARY KEY,
    provider TEXT NOT NULL,
    endpoint_key TEXT NOT NULL,
    method TEXT NOT NULL,
    path_template TEXT,
    path TEXT NOT NULL,
    ticker TEXT,
    params_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    status_code INTEGER,
    status_family TEXT NOT NULL,
    request_started_at TIMESTAMPTZ NOT NULL,
    request_finished_at TIMESTAMPTZ NOT NULL,
    latency_ms INTEGER NOT NULL,
    attempt INTEGER NOT NULL DEFAULT 0,
    run_id BIGINT REFERENCES uw_scan.scan_runs(run_id) ON DELETE SET NULL,
    job_name TEXT,
    provider_request_id TEXT,
    official_daily_count INTEGER,
    official_daily_limit INTEGER,
    official_minute_remaining INTEGER,
    official_minute_reset TEXT,
    error_message TEXT,
    inserted_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT external_api_requests_provider_check
        CHECK (provider IN ('uw', 'massive')),
    CONSTRAINT external_api_requests_method_check
        CHECK (method IN ('GET')),
    CONSTRAINT external_api_requests_status_family_check
        CHECK (status_family IN ('2xx', '3xx', '4xx', '5xx', 'transport_error')),
    CONSTRAINT external_api_requests_latency_nonnegative_check
        CHECK (latency_ms >= 0),
    CONSTRAINT external_api_requests_attempt_nonnegative_check
        CHECK (attempt >= 0)
);

CREATE INDEX IF NOT EXISTS external_api_requests_provider_started_idx
    ON uw_scan.external_api_requests (provider, request_started_at DESC);

CREATE INDEX IF NOT EXISTS external_api_requests_provider_ticker_started_idx
    ON uw_scan.external_api_requests (provider, ticker, request_started_at DESC);

CREATE INDEX IF NOT EXISTS external_api_requests_provider_endpoint_started_idx
    ON uw_scan.external_api_requests (provider, endpoint_key, request_started_at DESC);

CREATE INDEX IF NOT EXISTS external_api_requests_provider_status_started_idx
    ON uw_scan.external_api_requests (provider, status_family, request_started_at DESC);
