# Provider Request Monitoring Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a Postgres-backed request ledger for outbound UW and Massive calls, expose provider-day usage summaries, and populate the existing sidebar health counters.

**Architecture:** Create a new append-only `external_api_requests` table, repository methods for inserts plus provider-day summaries, and a durable telemetry recorder that writes through its own autocommit connection. Instrument `UwClient` and `MassiveOhlcProvider` at their HTTP boundaries so every provider response or transport error is recorded without committing partial scan data. Add read-only FastAPI routes for deeper audit views and wire `/api/health` to the current provider-day summary used by the sidebar.

**Tech Stack:** Python via `uv` (`pyproject.toml` allows 3.11+, project runtime uses 3.13), FastAPI/Pydantic v2, psycopg 3, Postgres JSONB, httpx MockTransport tests, Next.js/TypeScript generated from OpenAPI.

---

## Notes

- Do not pass secrets into telemetry rows. Store request params only after removing auth keys.
- Do not commit unless the user explicitly asks; use the commit steps below as checkpoint guidance only.
- Provider-day means 8:00 PM America/New_York to the next 8:00 PM America/New_York.
- Keep existing UW `api_request_audit` and `raw_payloads`; the new table is operational telemetry.
- Telemetry must survive scan rollbacks. Do not let client-side request recording commit the main scan transaction.
- Production coverage must include scheduler jobs, the volatility backfill background task, and convenience env entrypoints that create provider clients.

### Task 1: Add Ledger Migration, Constraints, And Insert Method

**Files:**
- Create: `src/uw_scan/storage/migrations/018_external_api_requests.sql`
- Modify: `src/uw_scan/storage/repository.py`
- Test: `tests/integration/storage/test_migrations.py`
- Test: `tests/integration/storage/test_provider_usage_repository.py`

**Step 1: Write migration test**

Add assertions that `external_api_requests` exists after all migrations and has indexes for provider/time, ticker, endpoint, and status family. Add assertions for check constraints on `provider`, `method`, `status_family`, `latency_ms`, and `attempt`.

Run:

```bash
uv run pytest tests/integration/storage/test_migrations.py -q
```

Expected: FAIL because the table does not exist.

**Step 2: Add migration**

Create `018_external_api_requests.sql`:

```sql
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
```

Run:

```bash
uv run pytest tests/integration/storage/test_migrations.py -q
```

Expected: PASS.

**Step 3: Add repository dataclasses and insert method test**

In `repository.py`, add small dataclasses:

- `ExternalApiRequestInsert`
- `ExternalApiUsageSummary`
- `ExternalApiBreakdownRow`
- `ExternalApiRequestRow`

Create `tests/integration/storage/test_provider_usage_repository.py` with a freshly migrated DB fixture like the existing storage repository tests, then add:

```python
def test_external_api_request_roundtrip_and_summary(repo: Repository):
    now = datetime(2026, 5, 14, 14, 0, tzinfo=UTC)
    request_id = repo.insert_external_api_request(
        provider="uw",
        endpoint_key="iv_rank",
        method="GET",
        path_template="/api/stock/{ticker}/iv-rank",
        path="/api/stock/TSLA/iv-rank",
        ticker="TSLA",
        params={},
        status_code=200,
        status_family="2xx",
        started_at=now,
        finished_at=now,
        latency_ms=42,
        official_daily_count=10,
        official_daily_limit=1000,
    )
    repo.conn.commit()
    assert request_id > 0
```

Run:

```bash
uv run pytest tests/integration/storage/test_provider_usage_repository.py::test_external_api_request_roundtrip_and_summary -q
```

Expected: FAIL because the method does not exist.

**Step 4: Implement insert method**

Add `Repository.insert_external_api_request(...)` using explicit parameters and `Jsonb(params)`. Keep it a thin insert wrapper like existing repository methods.

Run:

```bash
uv run pytest tests/integration/storage/test_provider_usage_repository.py::test_external_api_request_roundtrip_and_summary -q
```

Expected: PASS.

**Step 5: Checkpoint**

If explicitly asked to commit:

```bash
git add src/uw_scan/storage/migrations/018_external_api_requests.sql src/uw_scan/storage/repository.py tests/integration/storage/test_migrations.py tests/integration/storage/test_provider_usage_repository.py
git commit -m "feat: add external provider request ledger"
```

### Task 2: Add Provider-Day, Redaction, And Summary Queries

**Files:**
- Modify: `src/uw_scan/storage/repository.py`
- Test: `tests/unit/storage/test_provider_usage_helpers.py`
- Test: `tests/integration/storage/test_provider_usage_repository.py`

**Step 1: Write provider-day tests**

Add tests for:

- `provider_day_bounds(now)` returns the previous 8 PM ET when `now` is before 8 PM ET.
- `provider_day_bounds(now)` returns the same-day 8 PM ET when `now` is after 8 PM ET.
- `status_family_for(status_code)` returns `2xx`, `3xx`, `4xx`, or `5xx`.
- `status_family_for(None, error=True)` returns `transport_error`.
- `redact_params(...)` drops auth-like keys and truncates long values.
- summary counts `2xx`, `4xx`, `5xx`, `transport_error`.
- p95 latency is computed from ledger rows.
- latest UW official count/limit is taken from the newest UW row with header values.

Run:

```bash
uv run pytest tests/unit/storage/test_provider_usage_helpers.py tests/integration/storage/test_provider_usage_repository.py -q
```

Expected: FAIL because summary helpers do not exist.

**Step 2: Implement helpers and repository summaries**

Add helper functions near the repository layer:

- `provider_day_bounds(now: datetime | None = None) -> tuple[datetime, datetime]`
- `status_family_for(status_code: int | None, *, transport_error: bool = False) -> str`
- `redact_params(params: dict[str, object]) -> dict[str, object]`

Add in `repository.py`:

- `get_external_api_usage_summary(provider: str | None, start: datetime, end: datetime)`
- `list_external_api_endpoint_usage(provider: str | None, start: datetime, end: datetime)`
- `list_external_api_ticker_usage(provider: str | None, start: datetime, end: datetime)`
- `list_external_api_requests(...)`

Use SQL `FILTER` aggregates for counts and `percentile_cont(0.95)` for p95.

Run:

```bash
uv run pytest tests/unit/storage/test_provider_usage_helpers.py tests/integration/storage/test_provider_usage_repository.py -q
```

Expected: PASS.

**Step 3: Checkpoint**

If explicitly asked to commit:

```bash
git add src/uw_scan/storage/repository.py tests/unit/storage/test_provider_usage_helpers.py tests/integration/storage/test_provider_usage_repository.py
git commit -m "feat: summarize provider request usage"
```

### Task 3: Add Durable Telemetry Recorder

**Files:**
- Create: `src/uw_scan/storage/provider_usage.py`
- Modify: `src/uw_scan/api/deps.py`
- Test: `tests/integration/storage/test_provider_usage_recorder.py`
- Test: `tests/integration/api/conftest.py`

**Step 1: Write failing recorder tests**

Add tests that:

- recorder inserts a row through an autocommit connection.
- a rollback on the main scan connection does not erase a row written by the recorder.
- recorder failures are logged and swallowed so telemetry cannot break scans.

Run:

```bash
uv run pytest tests/integration/storage/test_provider_usage_recorder.py -q
```

Expected: FAIL because the recorder does not exist.

**Step 2: Implement recorder**

Create `ExternalApiRequestEvent` and `ExternalApiRequestRecorder`.

The recorder should own a dedicated psycopg connection with `autocommit=True`, wrap a `Repository`, and expose:

```python
def record(self, event: ExternalApiRequestEvent) -> None: ...
def close(self) -> None: ...
def __enter__(self) -> ExternalApiRequestRecorder: ...
def __exit__(self, *_exc) -> None: ...
```

It should catch/log exceptions inside `record` and never raise into provider clients.

**Step 3: Add API dependency helper**

In `api/deps.py`, add a generator dependency:

```python
def get_external_api_recorder() -> Generator[ExternalApiRequestRecorder, None, None]:
    ...
```

Tests should be able to override this dependency like `get_repo`.

Run:

```bash
uv run pytest tests/integration/storage/test_provider_usage_recorder.py -q
```

Expected: PASS.

**Step 4: Checkpoint**

If explicitly asked to commit:

```bash
git add src/uw_scan/storage/provider_usage.py src/uw_scan/api/deps.py tests/integration/storage/test_provider_usage_recorder.py tests/integration/api/conftest.py
git commit -m "feat: add durable provider request recorder"
```

### Task 4: Instrument UW Client

**Files:**
- Modify: `src/uw_scan/api/client.py`
- Modify: `src/uw_scan/sources/uw.py`
- Modify: `src/uw_scan/worker/scheduler.py`
- Modify: `src/uw_scan/api/routers/volatility.py`
- Modify: `src/uw_scan/pipeline.py`
- Test: `tests/unit/api/test_uw_client_telemetry.py`
- Test: `tests/integration/api/test_volatility_endpoint.py`

**Step 1: Write failing UW client telemetry tests**

Create tests with `httpx.MockTransport` covering:

- successful `2xx` writes one ledger row with endpoint slug, ticker, latency, and UW headers.
- `4xx` writes one ledger row before raising `UwHTTPError`.
- `5xx` with retry writes each HTTP attempt.
- every transport error attempt writes `transport_error`, including attempts that later retry.
- telemetry recorder exceptions do not change the `UwClient` response/exception behavior.

Run:

```bash
uv run pytest tests/unit/api/test_uw_client_telemetry.py -q
```

Expected: FAIL because `UwClient` cannot write telemetry yet.

**Step 2: Add optional recorder to `UwClient`**

Add constructor params:

- `telemetry_recorder: ExternalApiRequestRecorder | None = None`
- `job_name: str | None = None`

Add a private `_record_request(...)` helper. It should no-op when `telemetry_recorder` is `None`.

Write one ledger row per attempt after response or terminal transport failure. Do not include bearer token or secrets.

**Step 3: Pass run context from UW fetchers**

In `sources/uw.py`, pass `run_id` per call so one shared `UwClient` can safely scan many tickers:

```python
client.get(slug, ticker=ticker, params=params, run_id=run_id)
```

Adjust `UwClient.get` accordingly.

**Step 4: Wire production UW client construction**

Update every production `UwClient(...)` creation to pass a recorder when settings are available:

- `worker/scheduler.py` full scan, rescan, and nightly flow refresh
- `api/routers/volatility.py` background backfill
- `pipeline.py::run_single_stock_for_ticker_via_env`

Keep live tests and isolated direct client tests working by allowing `telemetry_recorder=None`.

Run:

```bash
uv run pytest tests/unit/api/test_uw_client_telemetry.py -q
uv run pytest tests/integration/test_scan_e2e.py -q
```

Expected: PASS.

**Step 5: Checkpoint**

If explicitly asked to commit:

```bash
git add src/uw_scan/api/client.py src/uw_scan/sources/uw.py src/uw_scan/worker/scheduler.py src/uw_scan/api/routers/volatility.py src/uw_scan/pipeline.py tests/unit/api/test_uw_client_telemetry.py tests/integration/api/test_volatility_endpoint.py
git commit -m "feat: record UW provider request telemetry"
```

### Task 5: Instrument Massive Provider

**Files:**
- Modify: `src/uw_scan/sources/ohlc.py`
- Modify: `src/uw_scan/worker/scheduler.py`
- Modify: `src/uw_scan/worker/volatility_jobs.py`
- Test: `tests/unit/sources/test_ohlc_provider.py`
- Test: `tests/integration/worker/test_volatility_jobs.py`

**Step 1: Extend Massive provider tests**

Add assertions that:

- `fetch_daily` records `provider="massive"`, `endpoint_key="daily_ohlc"`, ticker, status, latency.
- `fetch_intraday_quote` records `endpoint_key="intraday_quote"`.
- 404 records `4xx` even when the method returns `None`.
- raised HTTP errors still record rows.

Run:

```bash
uv run pytest tests/unit/sources/test_ohlc_provider.py -q
```

Expected: FAIL.

**Step 2: Implement Massive telemetry**

Add optional constructor args:

- `telemetry_recorder: ExternalApiRequestRecorder | None = None`
- `job_name: str | None = None`

Wrap each `_client.get(...)` call in start/end timing and insert a ledger row. Extract `request_id` from JSON when available, but tolerate invalid/empty JSON.

**Step 3: Wire worker provider construction**

In `worker/scheduler.py`, when creating `MassiveOhlcProvider`, pass a recorder and job name for:

- `spot_refresh`
- `ohlc_pull`
- `_full_scan` if it uses the OHLC provider later

In `worker/volatility_jobs.py`, thread the recorder into `daily_spy_ohlc_refresh`, because that function creates its own `MassiveOhlcProvider`.

Run:

```bash
uv run pytest tests/unit/sources/test_ohlc_provider.py -q
uv run pytest tests/integration/api/test_stock_ohlc_jobs.py -q
uv run pytest tests/integration/worker/test_volatility_jobs.py -q
```

Expected: PASS.

**Step 4: Checkpoint**

If explicitly asked to commit:

```bash
git add src/uw_scan/sources/ohlc.py src/uw_scan/worker/scheduler.py src/uw_scan/worker/volatility_jobs.py tests/unit/sources/test_ohlc_provider.py tests/integration/worker/test_volatility_jobs.py
git commit -m "feat: record Massive provider request telemetry"
```

### Task 6: Add Provider Usage API

**Files:**
- Create: `src/uw_scan/api/routers/provider_usage.py`
- Modify: `src/uw_scan/api/server.py`
- Test: `tests/integration/api/test_provider_usage.py`
- Test: `tests/integration/api/test_openapi_snapshot.py`

**Step 1: Write API tests**

Add tests for:

- summary endpoint returns current provider-day bounds and counts.
- endpoint breakdown groups by endpoint key.
- ticker breakdown groups by ticker.
- request list filters by provider/ticker/status family.
- invalid provider values return 422.
- requests endpoint is bounded with a default and maximum limit.

Run:

```bash
uv run pytest tests/integration/api/test_provider_usage.py -q
```

Expected: FAIL because route does not exist.

**Step 2: Implement Pydantic schemas and routes**

Create read-only router with:

- `GET /api/provider-usage/summary`
- `GET /api/provider-usage/endpoints`
- `GET /api/provider-usage/tickers`
- `GET /api/provider-usage/requests`

Validate provider as `uw`, `massive`, or `all`. Default all endpoints to current provider-day.

**Step 3: Register router and update OpenAPI snapshot**

Modify `server.py` to include the new router. Run snapshot update only if the project has an existing blessed workflow; otherwise run the snapshot test and update deliberately.

Run:

```bash
uv run pytest tests/integration/api/test_provider_usage.py tests/integration/api/test_openapi_snapshot.py -q
```

Expected: PASS after snapshot is updated.

**Step 4: Checkpoint**

If explicitly asked to commit:

```bash
git add src/uw_scan/api/routers/provider_usage.py src/uw_scan/api/server.py tests/integration/api/test_provider_usage.py tests/integration/api/openapi.snapshot.json
git commit -m "feat: expose provider usage API"
```

### Task 7: Wire Health Sidebar Stats

**Files:**
- Modify: `src/uw_scan/api/routers/health.py`
- Modify: `web/components/shared/HealthPanel.tsx`
- Test: `tests/integration/api/test_health.py`
- Test: `web/tests/unit/healthPanel.test.tsx`

**Step 1: Extend health API tests**

Seed provider request rows and assert `/api/health` returns:

- `latency_p95_ms`
- `http_2xx`
- `http_4xx`
- `http_5xx`
- `uw_today`
- health still includes usage fields when there is no successful full scan yet.

Run:

```bash
uv run pytest tests/integration/api/test_health.py -q
```

Expected: FAIL because health still returns placeholders.

**Step 2: Implement health summary wiring**

In `health.py`, fetch the provider-day summary and populate existing fields. Preserve current `ok/reason` behavior when no scans exist.

Run:

```bash
uv run pytest tests/integration/api/test_health.py -q
```

Expected: PASS.

**Step 3: Add/update HealthPanel test**

Create `web/tests/unit/healthPanel.test.tsx` if it does not exist. Mock `@/lib/api` and assert populated counts render, missing values render dashes, and the worker status remains unchanged.

**Step 4: Update HealthPanel if needed**

If adding an `UW Today` row, update `HealthPanel.tsx` and the generated type usage. Keep layout compact.

Run:

```bash
cd web && npm run test -- healthPanel
```

Expected: PASS.

**Step 5: Regenerate TypeScript types**

Start the FastAPI app on port 8400, then run:

```bash
cd web && npm run gen:types
```

Expected: `web/lib/types.ts` updates with provider usage schemas.

**Step 6: Checkpoint**

If explicitly asked to commit:

```bash
git add src/uw_scan/api/routers/health.py web/components/shared/HealthPanel.tsx web/lib/types.ts tests/integration/api/test_health.py web/tests/unit/healthPanel.test.tsx
git commit -m "feat: show provider usage in health panel"
```

### Task 8: Final Verification

**Files:**
- None unless tests expose issues.

**Step 1: Run backend tests**

```bash
uv run pytest
```

Expected: PASS.

**Step 2: Run frontend tests**

```bash
cd web && npm run test
```

Expected: PASS.

**Step 3: Run type generation check**

```bash
uv run uvicorn uw_scan.api.server:app --host 127.0.0.1 --port 8400
```

In a second terminal:

```bash
cd web && npm run gen:types
git diff -- web/lib/types.ts
```

Expected: either no diff or an intentional generated diff already staged.

**Step 4: Run migration idempotence check**

```bash
bash scripts/migrate.sh
bash scripts/migrate.sh
```

Expected: both runs complete without errors.

**Step 5: Manual smoke**

Run the app stack:

```bash
bash scripts/dev.sh
```

Trigger a health read and one scan/spot-refresh path, then check:

- sidebar shows non-dash provider counts after provider requests happen
- `GET /api/provider-usage/summary` returns provider-day totals
- provider usage rows contain no secrets

**Step 6: Final checkpoint**

If explicitly asked to commit:

```bash
git status --short
git add docs/superpowers/archive/specs/2026-05-14-provider-request-monitoring-design.md docs/superpowers/archive/plans/2026-05-14-provider-request-monitoring.md
git add src/uw_scan web tests
git commit -m "feat: monitor external provider requests"
```
