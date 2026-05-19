# Complexity Hotspots Optimization Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Reduce measured latency on the highest-confidence complexity hotspots without changing API contracts, persisted data shape, or UI behavior.

**Architecture:** Keep the optimization local to existing storage mixins, API routers, worker jobs, and chart components. Prefer batching and memoized derived data over broad rewrites. Add narrow behavioral tests first, then add a lightweight measurement script so before/after claims have evidence.

**Tech Stack:** Python via `uv` with project support for 3.11+, FastAPI, psycopg 3, pytest, Next.js 16, React 19, TypeScript, Vitest.

---

## Scope Guardrails

- Do not change table schemas, migrations, API response schemas, OpenAPI component names, or visible UI copy unless a test proves the change is required.
- Keep `src/uw_scan/storage/repository.py` thin; add or modify domain mixins only.
- Preserve all `ON CONFLICT` behavior and return counts from repository insert/upsert methods.
- Preserve row ordering in chart paths and API responses.
- Do not claim percentage or multiplier performance gains unless a live Postgres before/after benchmark ran in the same environment. If live DB benchmarking is unavailable, describe the win structurally as fewer round trips.
- Use milestone commits after each verified task.
- Run `git diff --check` before each commit.

## Baseline Commands

Run from the worktree root:

```bash
uv run pytest tests/integration/test_repository_real_pg.py tests/integration/api/test_health.py -q
cd web && npm run test
cd web && npm run typecheck
```

Expected: pass, or document pre-existing failures before touching implementation.

---

### Task 0: Capture Pre-Change Performance Baseline

**Files:**
- No code changes required.
- Optional scratch output only; do not commit environment-specific benchmark logs.

**Step 1: Record current hotspot inventory**

Run:

```bash
python3 /Users/chenxi/.codex/skills/complexity-optimizer/scripts/analyze_complexity.py /Users/chenxi/projects/unusual-whales/.claude/worktrees/chore+complexity-hotspots-plan --format json --exclude .venv --max-findings 1000
```

Expected: scanner still reports the storage write, health heartbeat, gold ingest, and chart render-derived-work hotspots this plan targets.

**Step 2: Run pre-change live DB benchmark if a disposable/local DB is available**

Run only when `UW_SCAN_DATABASE_URL` points to a database where temporary benchmark tables are acceptable:

```bash
uv run python scripts/bench_storage_batch_writes.py --mode live-postgres --rows 1000 --legacy-only
uv run python scripts/bench_storage_batch_writes.py --mode live-postgres --rows 10000 --legacy-only
```

Expected: benchmark prints single-row execute timing for the current implementation path. Capture the output for PR notes, but do not commit it.

If `scripts/bench_storage_batch_writes.py` does not exist yet, perform this baseline immediately after Task 1 creates the harness and before Task 2 changes repository writers.

**Step 3: Fallback when live DB benchmark is unavailable**

Document in the PR notes:

```text
Live Postgres benchmark unavailable in this environment; performance evidence is structural only: converted N per-row client/server calls to one executemany call per batch, with integration tests preserving DB behavior.
```

Do not include estimated percentage or multiplier gains in the PR unless Step 2 ran.

---

### Task 1: Add Measurement Harness For Batch Writes

**Files:**
- Create: `scripts/bench_storage_batch_writes.py`
- Test: `tests/unit/storage/test_batch_write_params.py`

**Step 1: Write the failing test**

Create a unit test that imports the parameter builders added in the next step and verifies they preserve row order and exact tuple values for a small set of model rows.

Run:

```bash
uv run pytest tests/unit/storage/test_batch_write_params.py -q
```

Expected: fail because the parameter builder module/function does not exist.

**Step 2: Add pure parameter builders**

Add small pure helpers near the target storage mixins, not in `repository.py`. Start with the largest repeated writers:

- `src/uw_scan/storage/options.py`
  - `_iv_term_params`
  - `_greek_exposure_params`
  - `_greeks_params`
  - `_option_contract_params`
- `src/uw_scan/storage/volatility_raw.py`
  - `_iv_rank_params`
  - `_volatility_stats_params`
  - `_realized_vol_params`
  - `_skew_params`
- `src/uw_scan/storage/flow.py`
  - `_flow_event_params`

Keep helpers private and deterministic. They should return `list[tuple[...]]` in input order.

**Step 3: Add benchmark script**

Create `scripts/bench_storage_batch_writes.py` with two modes:

- `--mode params-only` measures Python tuple-building overhead without a database.
- `--mode live-postgres` optionally runs against `UW_SCAN_DATABASE_URL` and compares single-row execute vs `executemany` on a temporary table.
- `--legacy-only` measures only the current single-row execute path so it can be used as a pre-change baseline before Task 2.

The script must not require secrets or run by default in CI.

**Step 4: Verify**

Run:

```bash
uv run pytest tests/unit/storage/test_batch_write_params.py -q
uv run python scripts/bench_storage_batch_writes.py --mode params-only --rows 10000
```

Expected: tests pass and script prints rows/sec for tuple construction.

If `UW_SCAN_DATABASE_URL` is available, also run:

```bash
uv run python scripts/bench_storage_batch_writes.py --mode live-postgres --rows 1000 --legacy-only
uv run python scripts/bench_storage_batch_writes.py --mode live-postgres --rows 10000 --legacy-only
```

Expected: script prints current single-row execute timings for PR comparison.

**Step 5: Commit**

```bash
git add scripts/bench_storage_batch_writes.py tests/unit/storage/test_batch_write_params.py src/uw_scan/storage/options.py src/uw_scan/storage/volatility_raw.py src/uw_scan/storage/flow.py
git commit -m "test(storage): add batch write measurement harness"
```

---

### Task 2: Convert Hot Repository Writers To `executemany`

**Files:**
- Modify: `src/uw_scan/storage/options.py`
- Modify: `src/uw_scan/storage/volatility_raw.py`
- Modify: `src/uw_scan/storage/flow.py`
- Test: `tests/unit/storage/test_batch_write_params.py`
- Existing integration tests:
  - `tests/integration/cards/test_matrix_state_db.py`
  - `tests/integration/api/test_cockpit_endpoint.py`
  - `tests/integration/test_repository_real_pg.py`

**Step 1: Add failing call-shape tests**

Extend the unit tests with a fake cursor/connection and assert the target methods call `cur.executemany(sql, params)` once for multi-row inputs and never call per-row `execute`.

Run:

```bash
uv run pytest tests/unit/storage/test_batch_write_params.py -q
```

Expected: fail because current code loops over `cur.execute`.

**Step 2: Add real DB behavior tests**

Add or extend integration tests so each converted method is covered by real Postgres behavior, not only fake cursor call shape. Cover:

- empty input returns `0` and performs no write
- first insert persists the expected rows
- duplicate rerun preserves `ON CONFLICT` semantics and does not create duplicates
- returned count remains compatible with the existing method contract
- persisted row values are identical to the pre-batch behavior, including ordering where callers observe it

Use existing integration suites where possible:

- `tests/integration/cards/test_matrix_state_db.py`
- `tests/integration/api/test_cockpit_endpoint.py`
- `tests/integration/test_repository_real_pg.py`
- `tests/integration/test_pipeline_e2e.py` for flow events if needed

Run the targeted test before implementation and confirm it fails for the new batching-specific assertions where appropriate.

**Step 3: Replace per-row execute loops**

For each hot writer, build `params = _*_params(...)`, return `0` when empty, then call `cur.executemany(sql, params)`. Preserve the exact SQL and conflict behavior.

Target first:

- `insert_iv_term_rows`
- `insert_greek_exposure_rows`
- `insert_greeks_rows`
- `insert_option_contract_rows`
- `upsert_iv_rank_rows`
- `upsert_volatility_stats_rows`
- `upsert_realized_vol_rows`
- `upsert_skew_rows`
- `insert_flow_events`

Defer low-volume one-row or tiny-list methods unless benchmark data says they matter.

**Step 4: Verify behavior**

Run:

```bash
uv run pytest tests/unit/storage/test_batch_write_params.py -q
uv run pytest tests/integration/cards/test_matrix_state_db.py tests/integration/api/test_cockpit_endpoint.py tests/integration/test_repository_real_pg.py tests/integration/test_pipeline_e2e.py -q
uv run python scripts/bench_storage_batch_writes.py --mode params-only --rows 10000
git diff --check
```

Expected: tests pass; benchmark output captured for PR evidence.

If `UW_SCAN_DATABASE_URL` is available, also run:

```bash
uv run python scripts/bench_storage_batch_writes.py --mode live-postgres --rows 1000
uv run python scripts/bench_storage_batch_writes.py --mode live-postgres --rows 10000
```

Expected: script prints single-row execute vs `executemany` timings from the same environment. Use these numbers for any percentage or multiplier claim.

**Step 5: Commit**

```bash
git add src/uw_scan/storage/options.py src/uw_scan/storage/volatility_raw.py src/uw_scan/storage/flow.py tests/unit/storage/test_batch_write_params.py
git commit -m "perf(storage): batch high-volume repository writes"
```

---

### Task 3: Bulk Fetch Worker Heartbeats In Health API

**Files:**
- Modify: `src/uw_scan/storage/health.py`
- Modify: `src/uw_scan/api/routers/health.py`
- Test: `tests/integration/api/test_health.py`

**Step 1: Write failing test**

Add a test that inserts several `worker_heartbeat` rows, calls a new `repo.get_heartbeats([...])`, and asserts it returns a `dict[str, datetime]` with missing names omitted.

Run:

```bash
uv run pytest tests/integration/api/test_health.py -q
```

Expected: fail because `get_heartbeats` does not exist.

**Step 2: Implement bulk repository method**

Add:

```python
def get_heartbeats(self, job_names: Iterable[str]) -> dict[str, datetime]:
    ...
```

Use one SQL query with `WHERE job_name = ANY(%s)` or an equivalent psycopg-safe array/list parameter. Return `{}` for an empty input list.

**Step 3: Update API router**

In `_worker_health_rows`, precompute all expected heartbeat names, fetch once, and populate rows from the returned mapping. Preserve labels, roles, indices, and lag calculation.

**Step 4: Verify**

Run:

```bash
uv run pytest tests/integration/api/test_health.py -q
uv run pytest tests/unit/api/test_stock_router.py -q
git diff --check
```

Expected: health tests pass and response shape remains stable.

**Step 5: Commit**

```bash
git add src/uw_scan/storage/health.py src/uw_scan/api/routers/health.py tests/integration/api/test_health.py
git commit -m "perf(health): fetch worker heartbeats in bulk"
```

---

### Task 4: Batch Gold Ingest Persistence Loops

**Files:**
- Modify: `src/uw_scan/storage/gold.py`
- Modify: `src/uw_scan/storage/gold_etf.py`
- Modify: `src/uw_scan/worker/jobs/gold_jobs.py`
- Test: `tests/integration/worker/test_gold_daily_jobs.py`
- Test: `tests/integration/worker/test_gold_periodic_jobs.py`

**Step 1: Write failing tests**

Add real DB persistence tests for the new bulk methods and job paths before implementation. Existing tests already verify persisted rows; extend them so they also verify rerun/idempotency behavior for:

- FRED daily macro rows
- GPR daily macro rows
- monthly macro rows
- ETF holdings daily rows
- ETF flows daily rows
- WGC monthly rows

Use mocks only where the behavior is about provider failure isolation or call boundaries, not as the primary proof of persistence correctness.

Run:

```bash
uv run pytest tests/integration/worker/test_gold_daily_jobs.py tests/integration/worker/test_gold_periodic_jobs.py -q
```

Expected: fail for assertions that depend on the new bulk methods or new idempotency coverage.

**Step 2: Add bulk repository methods**

Use the existing `insert_wgc_etf_monthly_rows` style in `src/uw_scan/storage/gold_etf.py` as the template.

Add only methods needed by the jobs:

- daily macro series rows
- monthly macro series rows
- ETF holdings daily rows
- ETF flows daily rows

Each method should take an iterable of row dicts or typed source rows plus shared metadata like `as_of` and `source`, build params once, and call `executemany`.

**Step 3: Update worker jobs**

Buffer provider output into lists per source/ticker, then call the new bulk repository method. Preserve existing exception boundaries so one provider/ticker failure does not abort unrelated work.

**Step 4: Verify**

Run:

```bash
uv run pytest tests/integration/worker/test_gold_daily_jobs.py tests/integration/worker/test_gold_periodic_jobs.py -q
uv run pytest tests/integration/api/test_gold_router_state.py tests/integration/api/test_gold_router_replay.py -q
git diff --check
```

Expected: tests pass, with no schema/API changes. Real DB assertions, not mocks alone, must prove persisted values and idempotency.

**Step 5: Commit**

```bash
git add src/uw_scan/storage/gold.py src/uw_scan/storage/gold_etf.py src/uw_scan/worker/jobs/gold_jobs.py tests/integration/worker/test_gold_daily_jobs.py tests/integration/worker/test_gold_periodic_jobs.py
git commit -m "perf(gold): batch ingest persistence writes"
```

---

### Task 5: Memoize High-Cost Gold And Cockpit Chart Derivations

**Files:**
- Modify: `web/components/gold/lens1/GoldHoldingsVsPriceChart.tsx`
- Modify: `web/app/cockpit/[ticker]/CockpitChart.tsx`
- Modify: `web/app/cockpit/[ticker]/CockpitDealerTab.tsx`
- Test: existing web test suite, add focused tests only if current harness covers these components cleanly

**Step 1: Confirm current behavior**

Run:

```bash
cd web && npm run test
cd web && npm run typecheck
```

Expected: pass before edits.

**Step 2: Memoize Gold chart data**

In `GoldHoldingsVsPriceChart.tsx`, use `useMemo` for:

- selected country set
- visible countries
- country color map
- flattened central-bank history points
- all date/domain arrays
- chart points and ticks

Replace repeated `colorForCountry(countryIso3, cbCountryHistory)` linear scans with `countryColorByIso3.get(countryIso3)`.

**Step 3: Memoize Cockpit chart data**

In `CockpitDealerTab.tsx`, precompute vanna/charm series arrays with `useMemo`. In `CockpitChart.tsx`, either document that callers must pass sorted points or add an `assumeSorted?: boolean` option and use it only where the caller already sorted by strike/date.

**Step 4: Verify**

Run:

```bash
cd web && npm run test
cd web && npm run typecheck
cd web && npm run lint
git diff --check
```

Then run browser verification on a non-default port and check Gold plus Cockpit pages with Playwright or the Browser plugin:

```bash
cd web && npm run dev -- --port 3011
```

Expected:

- Gold page renders the holdings/central-bank chart after toggling Strategic, All, None, and one individual country.
- Cockpit page renders dealer vanna/charm charts with non-empty SVG paths.
- No console errors are introduced.

**Step 5: Commit**

```bash
git add web/components/gold/lens1/GoldHoldingsVsPriceChart.tsx web/app/cockpit/[ticker]/CockpitChart.tsx web/app/cockpit/[ticker]/CockpitDealerTab.tsx
git commit -m "perf(web): memoize chart derivations"
```

---

### Task 6: Final Verification And PR Evidence

**Files:**
- Modify only if needed: `docs/plans/2026-05-19-complexity-hotspots-optimization.md`

**Step 1: Run full relevant backend checks**

```bash
uv run ruff check src/uw_scan tests scripts
uv run pytest
```

Expected: all non-live tests pass.

**Step 2: Run full relevant web checks**

```bash
cd web && npm run test
cd web && npm run typecheck
cd web && npm run lint
```

Expected: pass.

**Step 3: Capture benchmark evidence**

```bash
uv run python scripts/bench_storage_batch_writes.py --mode params-only --rows 10000
```

If `UW_SCAN_DATABASE_URL` is configured for a disposable/local database:

```bash
uv run python scripts/bench_storage_batch_writes.py --mode live-postgres --rows 1000
uv run python scripts/bench_storage_batch_writes.py --mode live-postgres --rows 10000
```

Record before/after numbers in the PR body. Do not commit environment-specific benchmark output.

Only state numeric speedups when live Postgres benchmark numbers exist for both pre-change and post-change paths. Otherwise, state the measured structural change: per-row `execute` calls were replaced with one `executemany` call per batch and behavior was verified through integration tests.

**Step 4: Self-review**

Check:

- No API schema diff unless intentionally documented.
- No ordering changes in charts or response lists.
- No new writes to `repository.py`.
- Batch methods preserve conflict clauses and transaction behavior.
- Gold ingest still isolates provider/ticker failures.
- Worktree has no unrelated files.

**Step 5: Commit final doc/evidence updates if any**

```bash
git add docs/plans/2026-05-19-complexity-hotspots-optimization.md
git commit -m "docs(perf): record complexity optimization verification"
```

Skip this commit if the plan document was not changed during execution.

---

## PR Guidance

PR title:

```text
perf: batch storage writes and memoize hot chart derivations
```

PR body must include:

- Top hotspots addressed.
- Exact tests run.
- Benchmark command and output summary.
- Statement that API contracts and OpenAPI output were not intentionally changed.
- Residual risk: batching changes Postgres call shape, so integration tests are the merge gate.

---

## Execution Evidence

Implemented on branch `chore/complexity-hotspots-plan` in worktree
`.claude/worktrees/chore+complexity-hotspots-plan`.

Milestone commits:

- `62bd997` — `test(storage): add batch write measurement harness`
- `553a7fa` — `perf(storage): batch high-volume repository writes`
- `22fcf74` — `perf(health): fetch worker heartbeats in bulk`
- `ab6c0c8` — `perf(gold): batch ingest persistence writes`
- `f5f864e` — `perf(web): memoize chart derivations`
- `2637a30` — `docs(perf): record complexity optimization verification`
- `36d052b` — `chore(perf): keep benchmark uv-invoked`

Verification run from the worktree:

- `uv run ruff check src/uw_scan tests scripts` — passed, `All checks passed!`
- `uv run pytest` — passed, `666 passed, 5 skipped in 355.90s`
- `cd web && npm run test` — passed, `36 passed (36)`, `221 passed (221)`
- `cd web && npm run typecheck` — passed
- `cd web && npx eslint 'components/gold/lens1/GoldHoldingsVsPriceChart.tsx' 'app/cockpit/[ticker]/CockpitChart.tsx' 'app/cockpit/[ticker]/CockpitDealerTab.tsx'` — passed
- `cd web && npm run lint` — failed on unrelated pre-existing scanner/regime files:
  `web/app/scanner/page.tsx`, `web/components/regime/CriSubTab.tsx`,
  `web/components/regime/GexSubTab.tsx`,
  `web/components/scanner/CandidateCard.tsx`, and
  `web/components/scanner/DiscoveredCard.tsx`. The changed chart files pass
  targeted ESLint.
- `uv run python scripts/bench_storage_batch_writes.py --mode params-only --rows 10000`
  — `best=0.000717s`, `median=0.000765s`, `rows_per_sec=13066925`.
- Live Postgres benchmark was skipped because `UW_SCAN_DATABASE_URL` was not set.
  No numeric DB speedup claim should be made from this run.
- Playwright browser check on `http://localhost:3011`:
  Gold chart rendered `24` non-empty SVG paths after Strategic/All/None/country
  toggles; Cockpit dealer rendered `6` non-empty chart polylines. Known health
  CORS noise appeared because the non-default web origin `3011` calls the API on
  `127.0.0.1:8400`; no unexpected chart/page errors were observed.

Complexity optimizer after-scan:

- Total scanner findings dropped from `552` baseline to `536`.
- `io-or-query-in-loop` dropped from `23` baseline to `15`.
- Targeted storage hits after scan:
  `storage/volatility_raw.py=0`, `storage/flow.py=0`,
  `worker/jobs/gold_jobs.py=1`.
- Remaining scanner findings are still leads rather than proof; this PR only
  claims structural reductions where tests verify behavior.
