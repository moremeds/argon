# Pipeline Benchmark Gauge

**Date:** 2026-05-25
**Status:** Design approved for implementation planning
**Surface:** Hidden benchmark view inside the existing HealthPanel
**Future integration:** Grafana-readable Postgres snapshots

---

## 1. Problem

The app already exposes useful operational signals through `/api/health`: worker
heartbeats, provider latency, request counts, scan duration, queue drain rate,
record coverage, and spot/WS freshness. The scanner page also has a domain
specific freshness model: fresh under 8h, stale under 72h, dead after 72h.

Those facts are visible as individual rows, but there is no single benchmark
that answers:

- Is the scanner pipeline healthy enough right now?
- Which layer is the bottleneck: freshness, coverage, throughput, provider,
  workers, or persistence?
- Is performance degrading over time?
- Can Grafana query the same facts later without scraping the Next app?

The first version should benchmark app/scanner pipeline performance only. It
must not mix in trading/signal realized returns.

## 2. Goals

1. Add a hidden Benchmark view within the existing HealthPanel.
2. Produce an explainable 0-100 Pipeline Benchmark score.
3. Show visible sub-scores so the headline is not opaque.
4. Persist benchmark snapshots to Postgres for trend analysis and future Grafana
   dashboards.
5. Keep Grafana compatibility first class: use typed numeric columns for common
   panels, with JSONB only for diagnostics and reasons.
6. Keep the normal HealthPanel polling path light.

## 3. Non-goals

- No realized trading performance, hit rate, forward return, or PnL tracking.
- No external observability stack in this PR.
- No Prometheus exporter yet.
- No redesign of the main scanner page.
- No dependency on Yahoo or any non-approved data fallback.
- No large generic metrics framework.

## 4. Product Shape

The existing HealthPanel remains the compact operational affordance in the
sidebar. When expanded, it gains a small Benchmark entry. Activating that entry
switches the panel body into a benchmark view.

The benchmark view shows:

| Section | Display |
|---|---|
| Headline | `Pipeline Benchmark`, score 0-100, status `OK` / `DEGRADED` / `CRITICAL` |
| Freshness | watchlist fresh %, scanner fresh/stale/dead/never-scanned, last full scan age |
| Coverage | active watchlist count, scanner fresh count, stale/dead/never-scanned counts |
| Throughput | average scan duration, p95 scan duration, queue drain rate, oldest queue age |
| Provider | UW p95 latency, 429 count, 4xx/5xx count, requests/min |
| Workers | scheduler/UW/Massive heartbeat state, WS tick age |
| Persistence | record coverage state and failing tables |
| Bottleneck | highest-penalty reason from the current score |

The view should fit the sidebar, not become a full dashboard. Detailed charting
is deferred to Grafana or a future dedicated admin page.

## 5. Scoring Model

Each sub-score is 0-100. The headline score is a weighted average:

| Component | Weight |
|---|---:|
| Freshness | 25 |
| Coverage | 20 |
| Throughput | 15 |
| Provider | 15 |
| Worker reliability | 15 |
| Persistence | 10 |

Suggested status bands:

| Score | Status |
|---:|---|
| 85-100 | OK |
| 60-84 | DEGRADED |
| 0-59 | CRITICAL |

Every score calculation stores reason codes and labels in `details_jsonb`, for
example:

```json
{
  "bottleneck": "coverage",
  "reasons": [
    {
      "component": "coverage",
      "severity": "degraded",
      "message": "71 of 102 scanner tickers are fresh"
    }
  ]
}
```

V1 should use simple deterministic thresholds. Avoid statistical baselines until
there is enough stored history to calibrate them.

## 6. Persistence

Create a new migration for a narrow snapshot table. As of 2026-05-25, the
latest migration in this checkout is `057_regime_backtest_results.sql`, so the
expected next slot is `058_pipeline_benchmark_snapshots.sql`. Re-verify before
implementation because parallel branches may land new migrations.

```sql
CREATE TABLE IF NOT EXISTS uw_scan.pipeline_benchmark_snapshots (
  id BIGSERIAL PRIMARY KEY,
  captured_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  capture_bucket TIMESTAMPTZ NOT NULL,
  score INTEGER NOT NULL CHECK (score BETWEEN 0 AND 100),
  status TEXT NOT NULL CHECK (status IN ('OK', 'DEGRADED', 'CRITICAL')),
  freshness_score INTEGER NOT NULL CHECK (freshness_score BETWEEN 0 AND 100),
  coverage_score INTEGER NOT NULL CHECK (coverage_score BETWEEN 0 AND 100),
  throughput_score INTEGER NOT NULL CHECK (throughput_score BETWEEN 0 AND 100),
  provider_score INTEGER NOT NULL CHECK (provider_score BETWEEN 0 AND 100),
  worker_score INTEGER NOT NULL CHECK (worker_score BETWEEN 0 AND 100),
  persistence_score INTEGER NOT NULL CHECK (persistence_score BETWEEN 0 AND 100),
  watchlist_size INTEGER CHECK (watchlist_size IS NULL OR watchlist_size >= 0),
  scanner_fresh_count INTEGER CHECK (scanner_fresh_count IS NULL OR scanner_fresh_count >= 0),
  scanner_stale_count INTEGER CHECK (scanner_stale_count IS NULL OR scanner_stale_count >= 0),
  scanner_dead_count INTEGER CHECK (scanner_dead_count IS NULL OR scanner_dead_count >= 0),
  scanner_never_scanned_count INTEGER CHECK (scanner_never_scanned_count IS NULL OR scanner_never_scanned_count >= 0),
  scan_duration_avg_seconds NUMERIC CHECK (scan_duration_avg_seconds IS NULL OR scan_duration_avg_seconds >= 0),
  scan_duration_p95_seconds NUMERIC CHECK (scan_duration_p95_seconds IS NULL OR scan_duration_p95_seconds >= 0),
  queue_depth INTEGER CHECK (queue_depth IS NULL OR queue_depth >= 0),
  oldest_queue_age_seconds NUMERIC CHECK (oldest_queue_age_seconds IS NULL OR oldest_queue_age_seconds >= 0),
  uw_latency_p95_ms INTEGER CHECK (uw_latency_p95_ms IS NULL OR uw_latency_p95_ms >= 0),
  uw_http_429 INTEGER CHECK (uw_http_429 IS NULL OR uw_http_429 >= 0),
  uw_http_4xx INTEGER CHECK (uw_http_4xx IS NULL OR uw_http_4xx >= 0),
  uw_http_5xx INTEGER CHECK (uw_http_5xx IS NULL OR uw_http_5xx >= 0),
  requests_per_minute NUMERIC CHECK (requests_per_minute IS NULL OR requests_per_minute >= 0),
  scheduler_heartbeat_lag_seconds NUMERIC CHECK (scheduler_heartbeat_lag_seconds IS NULL OR scheduler_heartbeat_lag_seconds >= 0),
  uw_worker_online_count INTEGER CHECK (uw_worker_online_count IS NULL OR uw_worker_online_count >= 0),
  uw_worker_expected_count INTEGER CHECK (uw_worker_expected_count IS NULL OR uw_worker_expected_count >= 0),
  massive_worker_online_count INTEGER CHECK (massive_worker_online_count IS NULL OR massive_worker_online_count >= 0),
  massive_worker_expected_count INTEGER CHECK (massive_worker_expected_count IS NULL OR massive_worker_expected_count >= 0),
  ws_tick_age_seconds NUMERIC CHECK (ws_tick_age_seconds IS NULL OR ws_tick_age_seconds >= 0),
  record_health_ok BOOLEAN,
  failing_record_tables TEXT[] NOT NULL DEFAULT '{}',
  details_jsonb JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_pipeline_benchmark_snapshots_captured_at
  ON uw_scan.pipeline_benchmark_snapshots (captured_at DESC);

CREATE INDEX IF NOT EXISTS idx_pipeline_benchmark_snapshots_status_time
  ON uw_scan.pipeline_benchmark_snapshots (status, captured_at DESC);

CREATE UNIQUE INDEX IF NOT EXISTS idx_pipeline_benchmark_snapshots_bucket
  ON uw_scan.pipeline_benchmark_snapshots (capture_bucket);
```

Design notes:

- The typed columns support Grafana panels directly.
- `capture_bucket` is the scheduler's rounded interval bucket, for example the
  current 5-minute bucket. It prevents duplicate rows if a job is registered or
  retried twice.
- `details_jsonb` captures reason codes, thresholds, and extra diagnostics.
- The table is append-only. Do not update historical snapshots.
- Retention is deferred. If the table grows too fast, add a retention policy in a
  follow-up PR.

## 7. Backend Architecture

Add a small benchmark domain, not more logic inside `repository.py`.

Suggested files:

| File | Purpose |
|---|---|
| `src/uw_scan/benchmark/pipeline.py` | Pure scoring and response assembly |
| `src/uw_scan/benchmark/collector.py` | DB-backed input collection from the warm store |
| `src/uw_scan/storage/pipeline_benchmark.py` | Insert/fetch snapshot rows |
| `src/uw_scan/api/routers/benchmark.py` or health sub-router | Read-only benchmark endpoints |
| `src/uw_scan/worker/jobs/pipeline_benchmark.py` | Scheduled snapshot capture |
| migration | `pipeline_benchmark_snapshots` table |

Keep `src/uw_scan/storage/repository.py` as an assembly/re-export shell only.

## 8. API

Use separate endpoints rather than adding heavy benchmark history to the
existing `/api/health` response:

```text
GET /api/health/benchmark/current
GET /api/health/benchmark/history?hours=24
```

`current` computes from live store state and may also return the most recent
persisted snapshot timestamp.

`history` reads persisted snapshots. Default to 24h, cap at a conservative
range such as 14d.

Response shape:

```json
{
  "captured_at": "2026-05-25T10:00:00Z",
  "score": 87,
  "status": "OK",
  "subscores": {
    "freshness": 92,
    "coverage": 88,
    "throughput": 81,
    "provider": 90,
    "worker": 100,
    "persistence": 75
  },
  "metrics": {
	    "watchlist_size": 102,
	    "scanner_fresh_count": 91,
	    "scanner_stale_count": 7,
	    "scanner_dead_count": 4,
	    "scanner_never_scanned_count": 0,
	    "queue_depth": 0,
	    "uw_latency_p95_ms": 412
	  },
  "bottleneck": {
    "component": "persistence",
    "message": "2 record-health tables below expected coverage"
  },
  "reasons": []
}
```

Regenerate `web/lib/types.ts` after adding API models.

## 9. Collection Model

V1 should support both:

1. On-demand current calculation for the HealthPanel view.
2. Scheduled snapshot persistence for trends and Grafana.

Scheduler cadence:

- every 5 minutes during market/session hours, or
- every 5 minutes all day if the current scheduler pattern makes that simpler.

The snapshot job should be cheap: it reads existing warm-store state and writes
one row. It must not call UW/Massive directly.

Schedule the job only on `role == "all"` or the primary UW worker
`role == "uw" and worker_index == 0`. In this repo, a generic primary-worker
check is not sufficient because every role can have index 0. The job should also
take a Postgres advisory lock before inserting so manual retries or accidental
double registration cannot create duplicate snapshots.

Scanner counts must be classified from the latest scanner-producing run per
active watchlist ticker without applying the API freshness cutoff first:

- `<8h`: fresh
- `8h` to `<72h`: stale
- `>=72h`: dead
- no scanner-producing run: never scanned

This distinction is required for coverage and freshness scoring; filtering out
old rows before classification would make dead tickers look missing or invisible.

## 10. Grafana Considerations

The table should be useful with a plain Postgres data source:

- time column: `captured_at`
- headline panel: `score`
- state panel: `status`
- component panels: `freshness_score`, `coverage_score`,
  `throughput_score`, `provider_score`, `worker_score`, `persistence_score`
- queue panels: `queue_depth`, `oldest_queue_age_seconds`
- provider panels: `uw_latency_p95_ms`, `uw_http_429`, `uw_http_5xx`
- worker panels: online vs expected counts, heartbeat lag, WS tick age

No Grafana-specific schema is needed. Avoid application-only nested JSON for
first-class chartable fields.

## 11. Testing

Backend:

- Unit tests for pure scoring thresholds and weighted score calculation.
- Unit tests for status band mapping.
- Integration tests for snapshot insert/fetch.
- API tests for `current` and `history`.
- OpenAPI snapshot update.

Frontend:

- HealthPanel unit test for opening the Benchmark view.
- Rendering test for OK/degraded/critical score states.
- Test empty/unavailable benchmark response handling.
- Type generation check.

Manual/browser:

- Start the local app.
- Expand HealthPanel.
- Open Benchmark.
- Confirm the score renders, sub-scores fit the sidebar, and text does not
  overlap on desktop and mobile widths.

## 12. Rollout

Implement in small PRs if needed:

1. Backend model, scoring, storage, API, and snapshot job.
2. HealthPanel benchmark view.
3. Grafana documentation snippets or SQL examples.

For the first PR, prefer one vertical slice if it remains small enough:
snapshot table, current endpoint, history endpoint, and hidden HealthPanel view.

## 13. Open Questions For Implementation

1. Exact freshness threshold for watchlist-card freshness versus scanner
   freshness. Scanner already has 8h/72h; watchlist-card should reuse the
   existing dashboard semantics.
2. Whether scan duration p95 should be computed from `scan_runs` directly in
   the benchmark helper or materialized into the snapshot table only. The
   implementation plan should add an explicit repository helper for this if the
   first UI displays p95.
3. Whether the scheduler should snapshot outside market hours and label market
   closed conditions explicitly in `details_jsonb`.
