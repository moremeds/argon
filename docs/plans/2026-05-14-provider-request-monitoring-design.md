# Provider Request Monitoring Design

## Goal

Track outbound Unusual Whales and Massive REST requests so the app can explain provider usage by status family, endpoint, ticker, and request time. Show the current provider-day totals in the lower-left health panel, and keep detailed request rows in Postgres for reference and audit.

## Scope

V1 tracks external provider calls only:

- Unusual Whales REST calls made through `UwClient`
- Massive REST calls made through `MassiveOhlcProvider`

V1 does not track this app's own internal API traffic, such as `/api/health`, `/api/watchlist`, or stock detail reads.

## Provider Day

Usage summaries use a provider-day window that resets at 8:00 PM America/New_York:

- start: the most recent 8:00 PM ET at or before `now`
- end: the next 8:00 PM ET

This aligns the sidebar and reports with daily provider usage accounting. It also avoids local-machine timezone drift when the app runs outside Eastern Time.

## Data Model

Create a new append-only ledger table, `uw_scan.external_api_requests`, as the shared usage telemetry model for both providers.

Suggested columns:

- `request_id BIGSERIAL PRIMARY KEY`
- `provider TEXT NOT NULL` with values `uw` and `massive`
- `endpoint_key TEXT NOT NULL`
- `method TEXT NOT NULL`
- `path_template TEXT`
- `path TEXT NOT NULL`
- `ticker TEXT`
- `params_json JSONB NOT NULL DEFAULT '{}'::jsonb`
- `status_code INTEGER`
- `status_family TEXT NOT NULL`
- `request_started_at TIMESTAMPTZ NOT NULL`
- `request_finished_at TIMESTAMPTZ NOT NULL`
- `latency_ms INTEGER NOT NULL`
- `attempt INTEGER NOT NULL DEFAULT 0`
- `run_id BIGINT REFERENCES uw_scan.scan_runs(run_id) ON DELETE SET NULL`
- `job_name TEXT`
- `provider_request_id TEXT`
- `official_daily_count INTEGER`
- `official_daily_limit INTEGER`
- `official_minute_remaining INTEGER`
- `official_minute_reset TEXT`
- `error_message TEXT`
- `inserted_at TIMESTAMPTZ NOT NULL DEFAULT now()`

Indexes:

- `(provider, request_started_at DESC)`
- `(provider, ticker, request_started_at DESC)`
- `(provider, endpoint_key, request_started_at DESC)`
- `(provider, status_family, request_started_at DESC)`

For UW, keep existing `api_request_audit` and `raw_payloads` as payload provenance. The new ledger is for operational usage, latency, and status accounting.

Add check constraints for the small enums and basic invariants:

- `provider IN ('uw', 'massive')`
- `method IN ('GET')` for V1
- `status_family IN ('2xx', '3xx', '4xx', '5xx', 'transport_error')`
- `latency_ms >= 0`
- `attempt >= 0`

Telemetry writes must be durable even when the scan transaction rolls back. Do not write request telemetry through the same transaction that owns scan persistence unless the caller explicitly commits only telemetry. Use a small telemetry recorder with its own autocommit connection per worker/API task so request rows survive failed scans without committing partial normalized data.

## Capture Points

### Unusual Whales

Instrument `UwClient.get(...)`.

Each outbound HTTP attempt should write one ledger row after a response or transport error. The existing UW fetchers still write raw payload audit rows only after a successful response has been parsed.

Captured fields:

- provider: `uw`
- endpoint key: existing `EndpointSlug`
- method: `GET`
- path template/path from the endpoint registry
- ticker if the endpoint uses one or params include ticker-like values
- status code/status family
- start/end/latency
- retry attempt number
- UW official headers: daily count, token request limit, minute remaining, minute reset
- transport error message when no HTTP response exists

### Massive

Instrument `MassiveOhlcProvider`.

V1 does not need official Massive reconciliation. Massive usage is tracked internally for throttle/debug visibility.

Captured fields:

- provider: `massive`
- endpoint key: `daily_ohlc` or `intraday_quote`
- method: `GET`
- path template/path
- ticker
- params
- status code/status family
- start/end/latency
- provider request id if Massive returns `request_id` in JSON
- transport or HTTP error message

## API Surface

Add read-only provider usage endpoints:

- `GET /api/provider-usage/summary?provider=uw|massive|all`
- `GET /api/provider-usage/endpoints?provider=uw|massive|all`
- `GET /api/provider-usage/tickers?provider=uw|massive|all`
- `GET /api/provider-usage/requests?provider=...&ticker=...&status_family=...`

All endpoints default to the current provider-day. Later versions can accept explicit `start` and `end`.

Summary fields:

- provider day start/end
- total request count
- `2xx`, `4xx`, `5xx`, `transport_error`
- p50/p95/p99 latency
- retry/throttle counts
- latest error
- UW official latest daily count/limit when available
- UW delta: latest official daily count minus internal UW count in the provider-day

Endpoint and ticker breakdowns return counts by status family and latency p95.

Request rows return the newest bounded list for audit/debug, with params redacted and no secrets.

Redaction rules are simple in V1: drop case-insensitive keys named `apiKey`, `apikey`, `api_key`, `token`, `authorization`, or `auth`, and truncate long string values before persistence.

## Sidebar

Wire `/api/health` to the ledger for the current provider-day and populate the existing fields:

- `latency_p95_ms`
- `http_2xx`
- `http_4xx`
- `http_5xx`
- `uw_today`

Keep the sidebar compact. It should remain a high-signal status panel, not a full audit screen.

Suggested display:

- `Source`: keep current source label or show `providers`
- `Latency p95`: combined provider-day p95
- `2xx`, `4xx`, `5xx`: combined provider-day totals
- `UW Today`: optional future row, rendered as `internal / official` when the header has appeared

## Testing

Python:

- migration creates the ledger table and indexes idempotently
- repository can insert request rows and summarize by provider-day
- provider-day helper handles before/after 8:00 PM ET
- `UwClient` records `2xx`, `4xx`, `5xx`, retry attempts, and transport errors with `httpx.MockTransport`
- `MassiveOhlcProvider` records daily and intraday requests with `httpx.MockTransport`
- `/api/health` returns populated status counts and latency
- provider usage endpoints return summary, endpoint, ticker, and request-row payloads

Web:

- HealthPanel renders populated counts and keeps dashes for missing values
- generated OpenAPI types stay in sync after adding provider usage routes

## Non-Goals

- No Redis or in-memory counters
- No request throttling changes in V1
- No official Massive usage reconciliation
- No tracking of internal app API traffic
- No migration of existing UW raw payload audit rows into the new table
