# Pipeline Benchmark Gauge Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a hidden HealthPanel benchmark view that scores app/scanner pipeline performance and persists Grafana-readable snapshots to Postgres.

**Architecture:** Implement a narrow vertical slice: pure benchmark scoring, a dedicated storage mixin/table, read-only benchmark endpoints, a scheduled snapshot job, generated web types, and a compact HealthPanel benchmark view. Keep `/api/health` lightweight by fetching benchmark data only when the hidden view is opened. Store chartable metrics in typed columns and diagnostic details in JSONB.

**Tech Stack:** Python 3.13 via `uv`, FastAPI, Pydantic v2, psycopg 3, Postgres migrations, APScheduler, Next.js 16, React 19, TypeScript, Vitest.

---

## Pre-flight

1. Create an isolated worktree from the current base branch before coding.
2. Verify the design exists:
   ```bash
   test -f docs/superpowers/specs/2026-05-25-pipeline-benchmark-gauge-design.md
   ```
3. Check migration prefixes before choosing the migration number:
   ```bash
   uv run python scripts/check_migration_prefixes.py
   ls src/uw_scan/storage/migrations/ | sort | tail -20
   ```
   Current verified assumption on 2026-05-25: `057_regime_backtest_results.sql`
   exists, so the next expected slot is `058_pipeline_benchmark_snapshots.sql`.
   Re-check immediately before writing the migration.
4. Do not commit unless the user explicitly asks. If commit permission is given, keep each closed task in its own commit.

## Task 1: Add Benchmark Models And Pure Scoring

**Files:**
- Create: `src/uw_scan/benchmark/__init__.py`
- Create: `src/uw_scan/benchmark/pipeline.py`
- Create or modify: `tests/unit/benchmark/test_pipeline.py`

**Step 1: Write failing scoring tests**

Test:

```python
from uw_scan.benchmark.pipeline import (
    BenchmarkInputs,
    ComponentScores,
    classify_status,
    compute_component_scores,
    weighted_score,
)


def test_weighted_score_uses_documented_weights() -> None:
    scores = ComponentScores(
        freshness=100,
        coverage=80,
        throughput=60,
        provider=40,
        worker=100,
        persistence=50,
    )
    assert weighted_score(scores) == 76


def test_classify_status_bands() -> None:
    assert classify_status(85) == "OK"
    assert classify_status(84) == "DEGRADED"
    assert classify_status(60) == "DEGRADED"
    assert classify_status(59) == "CRITICAL"


def test_coverage_penalizes_missing_scanner_tickers() -> None:
    inputs = BenchmarkInputs(
        watchlist_size=100,
        scanner_fresh_count=70,
        scanner_stale_count=20,
        scanner_dead_count=10,
        record_health_ok=True,
    )
    scores, reasons = compute_component_scores(inputs)
    assert scores.coverage < 80
    assert any(reason.component == "coverage" for reason in reasons)
```

**Step 2: Run tests to verify they fail**

Run:

```bash
uv run pytest tests/unit/benchmark/test_pipeline.py -q
```

Expected: fail because the module does not exist.

**Step 3: Implement pure models and scoring**

Create dataclasses or Pydantic models for:

- `BenchmarkInputs`
- `ComponentScores`
- `BenchmarkReason`
- `BenchmarkResult`

Implement:

- `classify_status(score: int) -> Literal["OK", "DEGRADED", "CRITICAL"]`
- `weighted_score(scores: ComponentScores) -> int`
- `compute_component_scores(inputs: BenchmarkInputs) -> tuple[ComponentScores, list[BenchmarkReason]]`
- `build_benchmark_result(inputs: BenchmarkInputs) -> BenchmarkResult`

Keep this module pure. It should not open DB cursors or call external providers.

**Step 4: Run tests to verify they pass**

Run:

```bash
uv run pytest tests/unit/benchmark/test_pipeline.py -q
```

Expected: pass.

## Task 2: Add Snapshot Migration And Storage Mixin

**Files:**
- Create: `src/uw_scan/storage/migrations/058_pipeline_benchmark_snapshots.sql` if still the next available migration slot
- Create: `src/uw_scan/storage/pipeline_benchmark.py`
- Modify: `src/uw_scan/storage/repository.py`
- Create or modify: `tests/integration/storage/test_pipeline_benchmark_repository.py`

**Step 1: Write failing storage tests**

Test insert and latest/history fetch:

```python
from datetime import UTC, datetime

from uw_scan.storage.repository import Repository


def test_pipeline_benchmark_snapshot_roundtrip(seeded_db_empty_cards: Repository) -> None:
    repo = seeded_db_empty_cards
    captured_at = datetime(2026, 5, 25, 12, 0, tzinfo=UTC)
    repo.insert_pipeline_benchmark_snapshot(
        captured_at=captured_at,
        capture_bucket=captured_at,
        score=87,
        status="OK",
        freshness_score=90,
        coverage_score=88,
        throughput_score=80,
        provider_score=91,
        worker_score=100,
        persistence_score=75,
        watchlist_size=102,
        scanner_fresh_count=91,
        scanner_stale_count=7,
        scanner_dead_count=4,
        scanner_never_scanned_count=0,
        details_jsonb={"bottleneck": "persistence"},
    )

    latest = repo.get_latest_pipeline_benchmark_snapshot()
    assert latest is not None
    assert latest.score == 87
    assert latest.details_jsonb["bottleneck"] == "persistence"
```

**Step 2: Run test to verify it fails**

Run:

```bash
uv run pytest tests/integration/storage/test_pipeline_benchmark_repository.py -q
```

Expected: fail because migration/storage helpers do not exist.

**Step 3: Add migration**

Use `058_pipeline_benchmark_snapshots.sql` only if it remains the next available
prefix after verifying the tree with `uv run python scripts/check_migration_prefixes.py`.
The table shape should match the design spec: typed Grafana columns,
`capture_bucket`, score/nonnegative `CHECK` constraints, a unique index on
`capture_bucket`, and `details_jsonb`.

**Step 4: Add storage mixin**

Create `_PipelineBenchmarkMixin` in `src/uw_scan/storage/pipeline_benchmark.py`.

Add methods:

- `insert_pipeline_benchmark_snapshot(...) -> int`
- `get_latest_pipeline_benchmark_snapshot() -> PipelineBenchmarkSnapshotRow | None`
- `list_pipeline_benchmark_snapshots(since: datetime, limit: int = 500) -> list[PipelineBenchmarkSnapshotRow]`

Add a row dataclass in `src/uw_scan/storage/rows.py` if that matches nearby storage patterns.

Modify `src/uw_scan/storage/repository.py` only to compose/re-export the mixin.

**Step 5: Run storage tests**

Run:

```bash
bash scripts/migrate.sh
uv run python scripts/check_migration_prefixes.py
uv run pytest tests/integration/storage/test_pipeline_benchmark_repository.py -q
```

Expected: pass.

## Task 3: Assemble Current Benchmark Inputs

**Files:**
- Modify: `src/uw_scan/benchmark/pipeline.py`
- Create: `src/uw_scan/benchmark/collector.py`
- Modify or create: `src/uw_scan/storage/pipeline_benchmark.py`
- Create or modify: `tests/integration/benchmark/test_pipeline_inputs.py`

**Step 1: Write failing integration test**

Seed enough watchlist, scan, job, provider, worker, and record-health state to
prove the assembler returns non-null core metrics without external calls.

Expected assertions:

- `watchlist_size` is populated.
- scanner fresh/stale/dead/never-scanned counts are populated.
- provider p95/429 metrics are populated when rows exist.
- queue depth and oldest queue age are populated.
- reasons mention the bottleneck when a component is degraded.

Also seed active watchlist tickers that cover all scanner states: `<8h` fresh,
`8h` to `<72h` stale, `>=72h` dead, and no scanner-producing run. The expected
counts must distinguish dead from never-scanned.

**Step 2: Add missing warm-store helpers**

Add storage helpers needed by the collector rather than hiding SQL in the API
router:

- `get_scan_duration_summary(start: datetime, end: datetime)`, returning avg
  and p95 seconds from `scan_runs`.
- `get_rescan_queue_summary()` already exists; use it for queue depth and
  oldest queued/running age.
- `count_pipeline_scanner_freshness(...)` or equivalent helper for scanner
  fresh/stale/dead/never-scanned counts.

Keep these helpers in storage domain modules, not in `repository.py`.

**Step 3: Implement input assembly**

Add `build_pipeline_benchmark_inputs(repo, settings, now_utc)` in
`src/uw_scan/benchmark/collector.py`. It reads from existing warm-store state
only:

- active watchlist count
- latest scanner-producing runs per active watchlist ticker without applying the
  API scanner freshness cutoff first; classify ages as `<8h` fresh, `8h` to
  `<72h` stale, `>=72h` dead, and `NULL` never-scanned
- external API usage summary for provider `uw`
- throughput summary
- worker heartbeat rows
- WS consumer state
- record-health rows
- jobs queue depth and oldest queued/running age

Do not call UW or Massive.

Do not put DB collection code in `src/uw_scan/benchmark/pipeline.py`; that file
stays pure scoring and result assembly.

**Step 4: Run tests**

Run:

```bash
uv run pytest tests/integration/benchmark/test_pipeline_inputs.py -q
```

Expected: pass.

## Task 4: Add Benchmark API Endpoints

**Files:**
- Create or modify: `src/uw_scan/api/routers/benchmark.py`
- Modify: `src/uw_scan/api/server.py`
- Modify: `tests/integration/api/test_health_benchmark.py`
- Modify: `tests/integration/api/openapi.snapshot.json`

**Step 1: Write failing API tests**

Test:

- `GET /api/health/benchmark/current` returns score, status, sub-scores, metrics, bottleneck/reasons.
- `GET /api/health/benchmark/history?hours=24` returns persisted snapshots.
- `hours` is capped and validated.

**Step 2: Implement endpoint models**

Use Pydantic response models. Keep endpoint routes under health:

```text
GET /api/health/benchmark/current
GET /api/health/benchmark/history
```

`current` computes live benchmark inputs and result.

`history` reads `pipeline_benchmark_snapshots`.

**Step 3: Update OpenAPI snapshot**

The benchmark routes are an API contract change. Regenerate the snapshot
unconditionally after the endpoint models are added:

```bash
uv run python - <<'PY'
import json
import os
from pathlib import Path

from uw_scan.api.server import create_app

os.environ.setdefault("UW_SCAN_API_KEY", "test-dummy-not-used-by-openapi")

Path("tests/integration/api/openapi.snapshot.json").write_text(
    json.dumps(create_app().openapi(), indent=2, sort_keys=True) + "\n"
)
PY
```

**Step 4: Run API tests**

Run:

```bash
uv run pytest tests/integration/api/test_health_benchmark.py -q
uv run pytest tests/integration/api/test_health.py -q
uv run pytest tests/integration/api/test_openapi_snapshot.py -q
```

Expected: pass.

## Task 5: Add Scheduled Snapshot Job

**Files:**
- Create: `src/uw_scan/worker/jobs/pipeline_benchmark.py`
- Modify: `src/uw_scan/worker/scheduler.py`
- Create or modify: `tests/unit/worker/test_pipeline_benchmark_job.py`

**Step 1: Write failing job test**

Test the job:

- computes current benchmark
- inserts one snapshot
- never calls external providers
- uses a Postgres advisory lock before insert so concurrent/manual runs do not
  duplicate snapshots
- logs and re-raises or records failures using the repo's established exception
  logging guardrails

Also test scheduler registration separately:

- `role == "all"` schedules the job.
- `role == "uw"` and `worker_index == 0` schedules the job.
- `role == "uw"` and `worker_index != 0` does not schedule the job.
- `role == "massive"`, `role == "ai-codex"`, and `role == "ai-claude"` do not
  schedule the job even when their worker index is 0.

**Step 2: Implement job**

Add a job function such as:

```python
def pipeline_benchmark_snapshot_job(settings: Settings | None = None) -> int:
    ...
```

Return the inserted snapshot id.

**Step 3: Register scheduler job**

Add a conservative 5-minute cadence behind a dedicated helper such as
`_should_schedule_pipeline_benchmark(settings)`. Do not rely on a generic
`_is_primary_worker()` check: every worker role can have index 0 in this repo.
Prefer scheduling only when `role == "all"` or when
`role == "uw" and worker_index == 0`.

The job itself should still acquire a Postgres advisory lock before insert.
The migration's unique `capture_bucket` index is the final duplicate guard.

**Step 4: Run worker tests**

Run:

```bash
uv run pytest tests/unit/worker/test_pipeline_benchmark_job.py -q
uv run pytest tests/unit/worker/test_scheduler.py -q
uv run ruff check src/uw_scan/worker src/uw_scan/benchmark src/uw_scan/storage tests/unit/worker/test_pipeline_benchmark_job.py
```

Expected: pass.

## Task 6: Generate Types And Add Web API Helpers

**Files:**
- Modify: `web/lib/api.ts`
- Modify: `web/lib/types.ts`
- Create or modify: `web/tests/unit/healthBenchmarkApi.test.ts`

**Step 1: Add failing web API helper test**

Test that helper functions call:

- `/api/health/benchmark/current`
- `/api/health/benchmark/history?hours=24`

**Step 2: Regenerate types**

Run:

```bash
cd web && npm run gen:types
```

Expected: `web/lib/types.ts` includes benchmark response schemas.

**Step 3: Add API helpers**

Add typed helpers to `web/lib/api.ts`.

**Step 4: Run web unit test**

Run:

```bash
cd web && npm run test -- healthBenchmarkApi
```

Expected: pass.

## Task 7: Add Hidden Benchmark View To HealthPanel

**Files:**
- Modify: `web/components/shared/HealthPanel.tsx`
- Create or modify: `web/tests/unit/healthPanel.test.tsx`

**Step 1: Write failing UI tests**

Tests:

- expanded HealthPanel shows a Benchmark control
- clicking Benchmark fetches current benchmark
- OK/degraded/critical states render with the right labels
- unavailable benchmark response renders a compact fallback

Update the existing API mock in `web/tests/unit/healthPanel.test.tsx` so it
includes the new benchmark API helpers as well as the existing `health` helper.

**Step 2: Implement UI**

Keep the normal status view intact. Add a simple local view mode:

```ts
type PanelView = "status" | "benchmark";
```

Only fetch benchmark data when `PanelView === "benchmark"` and the panel is
expanded.

Keep the view compact:

- headline score
- six sub-score rows
- bottleneck row
- a small back/status control

Avoid charting in V1.

**Step 3: Run UI tests**

Run:

```bash
cd web && npm run test -- healthPanel
cd web && npm run typecheck
```

Expected: pass.

## Task 8: Browser Verification

**Files:**
- No source files unless visual defects are found.

**Step 1: Start app**

Run the repo's normal dev command:

```bash
bash scripts/dev.sh
```

Use a non-conflicting port if the default web port is occupied.

**Step 2: Verify in browser**

Open the local app and check:

- HealthPanel collapsed state remains unchanged.
- Expanding HealthPanel still shows existing status rows.
- Benchmark view opens only from the expanded panel.
- Benchmark score and sub-scores fit without overlap.
- Empty/unavailable benchmark data does not break the panel.

**Step 3: Stop dev processes**

Stop only the processes started for this verification.

## Task 9: Final Verification

Run focused gates:

```bash
uv run python scripts/check_migration_prefixes.py
uv run pytest tests/unit/benchmark tests/integration/benchmark tests/integration/api/test_health_benchmark.py -q
uv run pytest tests/integration/storage/test_pipeline_benchmark_repository.py -q
uv run pytest tests/integration/api/test_openapi_snapshot.py -q
uv run pytest tests/unit/worker/test_pipeline_benchmark_job.py tests/unit/worker/test_scheduler.py -q
uv run ruff check src/uw_scan/benchmark src/uw_scan/storage/pipeline_benchmark.py src/uw_scan/api/routers/benchmark.py src/uw_scan/worker/jobs/pipeline_benchmark.py tests
```

With the API running on `127.0.0.1:8400`, refresh and verify the web contract:

```bash
cd web && npm run gen:types
cd web && npm run test -- healthPanel
cd web && npm run typecheck
```

Then inspect:

```bash
git status --short
git diff --stat
```

Expected: only benchmark design, plan, backend benchmark files, API/router
changes, migration, tests, generated types, and HealthPanel/API helper changes.

## Execution Choice

Plan complete and saved to `docs/plans/2026-05-25-pipeline-benchmark-gauge.md`.

Two execution options:

1. Subagent-Driven in this session: dispatch a fresh subagent per task, review
   between tasks, fast iteration.
2. Parallel Session: open a separate session in the worktree with
   `superpowers:executing-plans` and execute with checkpoints.
