# Complexity Reduction Round 2 Implementation Plan

> **For the implementer:** Execute task-by-task with milestone commits after targeted verification. Use any locally available execution-plan workflow only if it is allowed in the current agent/runtime; this plan is self-contained and does not require reading external skill definitions.

**Goal:** Reduce the six remaining complexity hotspots identified after PR #72 while preserving API contracts, UI behavior, persisted data semantics, and release safety.

**Architecture:** Optimize real runtime complexity first, then split large modules along existing domain boundaries. Keep public entry points stable: `assemble_trade_insights`, `build_rates_snapshot`, `/api/health`, `MultiLineChart`, and React page routes must keep their current behavior unless a task explicitly adds an internal helper.

**Recommended PR shape:** implement Tasks 1-3 as one runtime-performance PR, then Tasks 4-6 as one structural-complexity PR. A single branch may execute all six tasks in order, but split the review/merge if the combined diff becomes hard to review or rollback.

**Tech Stack:** Python 3.13 via `uv`, FastAPI/Pydantic v2, psycopg 3, pytest, Next.js 16/React 19/TypeScript, Vitest, ESLint.

---

## Ground Rules

- Work in a dedicated worktree and branch, not the main checkout.
- Do not use Docker.
- Use `uv` for Python commands only.
- Preserve public response models and OpenAPI component names.
- Preserve UI layout and visible behavior unless the task explicitly says otherwise.
- Commit after every milestone once its targeted verification passes.
- If a task touches DB-backed integration behavior, run integration tests sequentially.
- Do not touch unrelated staged/untracked files in the base checkout.
- Before creating a worktree, inspect the base checkout and confirm any existing dirty files are unrelated to this plan.

## Setup

**Step 1: Create isolated worktree**

Run:

```bash
cd /Users/chenxi/projects/unusual-whales
git status --short
git fetch origin
git worktree add .worktrees/complexity-reduction-round-2 -b chore/complexity-reduction-round-2 origin/main
cd .worktrees/complexity-reduction-round-2
```

Expected: base checkout dirty files, if any, are acknowledged as unrelated; new worktree on `chore/complexity-reduction-round-2`.

**Step 2: Confirm clean baseline**

Run:

```bash
git status --short --branch
uv run pytest tests/test_trade_insights.py -q
(cd web && npm run test -- tradeInsightsAiAnalysisPanel healthPanel)
```

Expected: clean branch, targeted tests pass.

**Step 3: Confirm task-specific anchors still exist**

Run:

```bash
rg -n "def fetch_pending|class TradeInsightOutcomeRepository" src/uw_scan/storage/trade_insight_outcomes_repository.py
rg -n "record_health|def health" src/uw_scan/api/routers/health.py tests/integration/api/test_health.py
rg -n "MultiLineChart|CockpitChart" web/app/cockpit web/tests
```

Expected: all commands find the anchors named in the plan. If a command returns nothing, stop and update this plan before coding.

---

## Task 1: Trade Insights Candidate Indexing

**Files:**
- Modify: `src/uw_scan/reports/trade_insights.py`
- Test: `tests/test_trade_insights.py`

**Why:** `_atm_straddles_by_expiry` repeatedly filters all contracts per expiry, and calendar spread construction uses a near-leg x far-leg nested scan. This is real algorithmic complexity on option-chain-sized inputs.

**Step 1: Add regression tests for ordering and calendar selection**

In `tests/test_trade_insights.py`, add tests that prove:

- ATM straddles still choose same-strike call/put nearest spot per expiry.
- ATM tie handling preserves current stable input-order behavior for equal-distance strikes and duplicate contracts.
- Calendar spread still picks the first valid near-to-far pair from the existing `calls` order and `far_calls` order.
- Candidate idea ordering remains stable.

Use existing fixtures in this file where possible. If new helpers are needed, keep them local to the test file.

Run:

```bash
uv run pytest tests/test_trade_insights.py -q
```

Expected: PASS before implementation if behavior is already covered; otherwise new assertions should expose any missing contract.

**Step 2: Introduce a private contract index helper**

In `src/uw_scan/reports/trade_insights.py`, add a small helper near `_normalized_contracts`:

```python
def _contracts_by_expiry_right_strike(
    contracts: list[dict],
) -> dict[date, dict[str, dict[Decimal, list[dict]]]]:
    index: dict[date, dict[str, dict[Decimal, list[dict]]]] = {}
    for contract in contracts:
        if contract.get("mid") is None:
            continue
        parsed: ParsedOptionSymbol = contract["parsed"]
        index.setdefault(parsed.expiry, {}).setdefault(parsed.right, {}).setdefault(
            parsed.strike, []
        ).append(contract)
    return index
```

**Step 3: Replace `_atm_straddles_by_expiry` repeated scans**

Change `_atm_straddles_by_expiry` to build the index once and iterate expiry groups. Preserve:

- skip when spot is missing
- skip when no matching call/put
- only emit when selected call and put have the same strike
- only use contracts with non-null `mid`

**Step 4: Replace calendar nested scan**

Inside `_build_candidates`, replace:

```python
calendar_pairs = [
    (near, far)
    for near in calls
    for far in far_calls
    if near["parsed"].strike == far["parsed"].strike
    and near["parsed"].expiry < far["parsed"].expiry
]
```

with a strike-keyed lookup over far calls. Preserve the current first-valid-pair ordering from `calls`.

The far-call lookup must preserve `far_calls` list order per strike. Do not replace current behavior with "earliest expiry" or any other semantic ordering unless the pre-implementation regression tests prove that is already the effective behavior.

**Step 5: Verify targeted behavior**

Run:

```bash
uv run pytest tests/test_trade_insights.py -q
uv run pytest tests/test_trade_insights_ai.py -q
uv run ruff check src/uw_scan/reports/trade_insights.py tests/test_trade_insights.py
```

Expected: all pass.

**Step 6: Commit**

Run:

```bash
git add src/uw_scan/reports/trade_insights.py tests/test_trade_insights.py
git commit -m "perf: index trade insight candidate contracts"
```

---

## Task 2: Trade Insight Outcome Backfill Bulk Reads

**Files:**
- Modify: `src/uw_scan/worker/jobs/trade_insight_outcome_backfill.py`
- Modify: `src/uw_scan/storage/trade_insight_outcomes_repository.py`
- Test: existing worker/storage tests under `tests/unit/worker/`, `tests/integration/worker/`, or add a focused integration test if no direct coverage exists.

**Why:** `_score_pending_rows` fetches the source analysis, forward closes, and snapshot close once per pending outcome. That creates query-in-loop behavior during backfill.

**Step 1: Locate existing outcome backfill tests**

Run:

```bash
rg -n "outcome_backfill|fetch_pending|trade_insight_outcome" tests src/uw_scan
```

Expected: identify the narrowest existing tests. If no focused test covers `_score_pending_rows`, add one using a fake repository at the worker boundary or a real Postgres fixture already used in this repo.

Do not invent an in-memory DB substitute for psycopg/Postgres behavior. This repo's persistence tests use real Postgres fixtures; if behavior depends on SQL ordering, `jsonb`, intervals, or transactions, add/extend an integration test instead of a fake connection test.

**Step 2: Add failing query-count or behavior test**

Add a test that seeds at least two pending rows for the same ticker and verifies scoring behavior is unchanged. The performance behavior must be proven, not inferred:

- repository/helper test: one pending-analysis fetch returns both pending rows
- OHLC bulk path test: one forward-close range fetch per ticker, not per row
- snapshot-close path test: snapshot closes are fetched in bulk or derived from the same bulk close set

If SQL query-count assertions are too brittle, instrument fake worker-boundary helpers so the test still fails if the implementation reintroduces per-row analysis or OHLC reads.

**Step 3: Add joined pending fetch helper**

Create a helper in `src/uw_scan/storage/trade_insight_outcomes_repository.py` that returns pending outcome rows with ticker/provider/prompt/outcome JSON in one query. Keep the existing `fetch_pending()` method unless all callers are migrated; add a new method rather than changing the existing tuple return shape.

Shape:

```python
@dataclass(frozen=True)
class PendingOutcomeAnalysis:
    analysis_id: UUID
    snapshot_date: date
    ticker: str
    provider: str
    prompt_version: str
    outcome_jsonb: dict[str, Any]
```

The SQL should left join `trade_insight_outcomes` to `trade_insight_ai_analyses` on `analysis_id`, preserve the current pending filter (`resolved_outcome IS NULL OR resolved_outcome = 'pending'`), and preserve oldest-first ordering by `last_evaluated_at ASC, snapshot_date ASC`.

Use schema qualification deliberately. Current worker SQL references `uw_scan.trade_insight_ai_analyses`; repository methods often rely on the configured search path. The new helper should either follow the repository convention consistently or qualify both tables explicitly.

**Step 4: Bulk fetch closes by ticker**

Group pending rows by ticker. For each ticker, fetch closes from the minimum snapshot date to max snapshot date plus horizon once, then slice in memory for each pending row.

Also remove the per-row snapshot-close lookup. Either derive snapshot close from the grouped close set or add a bulk snapshot-close helper keyed by `(ticker, snapshot_date)`.

Preserve:

- rows with missing analysis stay pending with warning
- recent rows with no forward bars stay partially scored
- fixed-window semantics in `_fixed_window_closes`
- trigger/target/stop scoring direction rules
- pending-row ordering and per-row update behavior
- transaction behavior; do not introduce a long transaction that holds locks across the whole batch unless a test proves it is safe

**Step 5: Verify targeted tests**

Run:

```bash
uv run pytest tests/unit/worker/ -q -k "outcome or trade_insight"
uv run pytest tests/integration/storage/test_repository_trade_insights_ai.py -q
uv run pytest tests/integration/worker/test_trade_insights_ai_jobs.py -q
uv run ruff check src/uw_scan/worker/jobs/trade_insight_outcome_backfill.py
```

Expected: all pass.

**Step 6: Commit**

Run:

```bash
git add src/uw_scan/worker/jobs/trade_insight_outcome_backfill.py src/uw_scan/storage/trade_insight_outcomes_repository.py tests/unit tests/integration
git commit -m "perf: batch trade insight outcome backfill reads"
```

---

## Task 3: Health Endpoint Poll Cost Reduction

**Files:**
- Modify: `src/uw_scan/api/routers/health.py`
- Modify: `src/uw_scan/storage/health.py` if needed
- Modify: `web/components/shared/HealthPanel.tsx` only if UI state needs a timestamp
- Test: `tests/integration/api/test_health.py`
- Test: `web/tests/unit/healthPanel.test.tsx`

**Why:** `HealthPanel` polls every 5 seconds, and the backend record-health path runs one aggregate query per selected table. This is unnecessary load for an always-visible panel.

**Step 1: Add test for stable cached record health**

Add or extend `tests/integration/api/test_health.py` to call the health endpoint twice with record coverage enabled and assert the response shape remains identical enough for the UI. If direct cache internals are hard to assert, add unit-level coverage for the cache object.

Also add a test-isolation hook: the cache must be clearable between tests so a cached record-health result cannot leak across `test_health_*` cases that seed different tables.

**Step 2: Implement a short TTL cache for record health**

Add a small in-process cache in `api/routers/health.py`, scoped to record-health table selection, min coverage, and window hours.

Rules:

- TTL: 15 seconds.
- Use an explicit helper object or small module-level functions such as `_record_health_cache_get`, `_record_health_cache_set`, and `_record_health_cache_clear_for_tests`.
- Do not cache DB-down failures as healthy.
- Do not cache exceptions from `repo.list_record_health`.
- Keep `ok`, `record_health`, and `record_health_ok` response fields unchanged.
- Cache only the expensive record-health block, not worker heartbeats or API status.
- Include `record_tables`, `record_window_hours`, `record_min_coverage`, `watchlist_size`, and `settings.record_health_daily_window_hours` in the cache key.
- Cached `window_start` and daily `window_start` may be up to 15 seconds stale by design. Add a test that proves this TTL behavior is bounded and does not leak across test cases after the test clear hook runs.
- Preserve exception behavior: `ValueError` still returns HTTP 400 through the existing path, and DB/runtime errors from `repo.list_record_health` still bubble as they do today. Do not cache exceptions.

**Step 3: If UI needs clarity, add non-disruptive timestamp**

Only if the backend response already exposes enough metadata, display nothing new. Avoid layout changes.

**Step 4: Verify**

Run:

```bash
uv run pytest tests/integration/api/test_health.py -q
(cd web && npm run test -- healthPanel)
(cd web && npm run typecheck)
(cd web && npm run lint)
```

Expected: all pass.

**Step 5: Commit**

Run:

```bash
git add src/uw_scan/api/routers/health.py src/uw_scan/storage/health.py web/components/shared/HealthPanel.tsx tests/integration/api/test_health.py web/tests/unit/healthPanel.test.tsx
git commit -m "perf: cache expensive health coverage checks"
```

---

## Task 4: Split Rates Backend Snapshot Assembler

**Files:**
- Modify: `src/uw_scan/rates/snapshot.py`
- Create: `src/uw_scan/rates/policy.py`
- Create: `src/uw_scan/rates/supply.py`
- Create: `src/uw_scan/rates/positioning.py`
- Create: `src/uw_scan/rates/synthesis.py` only if it removes real coupling
- Test: `tests/unit/rates/test_snapshot.py`
- Contract test: `tests/integration/api/test_openapi_snapshot.py`

**Why:** `snapshot.py` is 944 lines and mixes policy, supply, positioning, source freshness, and summary orchestration. This is maintainability complexity, not primarily runtime complexity.

**Step 1: Capture current behavior**

Run:

```bash
uv run pytest tests/unit/rates/test_snapshot.py -q
uv run pytest tests/integration/api/test_openapi_snapshot.py -q
uv run ruff check src/uw_scan/rates/
```

Expected: pass.

**Step 2: Move positioning helpers**

Move these functions into `src/uw_scan/rates/positioning.py`:

- `_positioning_panel`
- `_sum_attr`
- `_basis_proxy`
- `_positioning_read`
- `_contracts_text`
- `_positioning_status`

Export a public internal helper:

```python
def build_positioning_panel(...) -> RatesPositioningPanel:
    ...
```

Keep `snapshot.py` calling the new helper.

Do not move `_latest_float` into `positioning.py` or `policy.py`. It is used by top-level scorecard, supply, and policy today. Leave it in `snapshot.py` or move it to a shared internal helper module only after all extracted modules' dependencies prove that ownership.

**Step 3: Run narrow test**

Run:

```bash
uv run pytest tests/unit/rates/test_snapshot.py -q
uv run ruff check src/uw_scan/rates/
```

Expected: pass.

**Step 4: Commit positioning split**

Run:

```bash
git add src/uw_scan/rates/snapshot.py src/uw_scan/rates/positioning.py
git commit -m "refactor: split rates positioning snapshot builder"
```

**Step 5: Move supply helpers**

Move these functions into `src/uw_scan/rates/supply.py`:

- `_supply_panel`
- `_auction_payload`
- `_select_display_auctions`
- `_supply_summary_tiles`
- `_auction_amount_sum`
- `_bill_share`
- `_supply_fiscal_tiles`
- `_trillion`
- `_supply_read`
- `_has_live_debt_tile`
- `_auction_tone`

Expose `build_supply_panel(...)`.

**Step 6: Verify and commit supply split**

Run:

```bash
uv run pytest tests/unit/rates/test_snapshot.py -q
uv run ruff check src/uw_scan/rates/
git add src/uw_scan/rates/snapshot.py src/uw_scan/rates/supply.py
git commit -m "refactor: split rates supply snapshot builder"
```

**Step 7: Move policy helpers**

Move these functions into `src/uw_scan/rates/policy.py`:

- `_policy_panel`
- `_policy_status`
- `_has_live_plumbing_tile`
- `_latest_policy_meeting`
- `_format_target_range`
- `_infer_policy_action_from_targets`
- `_latest_decimal_on_or_before`
- `_latest_decimal_before`
- `_policy_read`
- `_path_read`
- `_plumbing_read`
- `_plumbing_tiles`
- `_walcl_qualifier`
- `_reserve_qualifier`
- `_rrp_qualifier`
- `_tga_qualifier`
- `_window_delta`
- `_latest_float` only if it has first been moved to a shared internal helper module and all callers are updated deliberately

Expose `build_policy_panel(...)`.

Stop after positioning, supply, and policy are extracted unless `snapshot.py` still exceeds 500 lines or has a clear remaining cohesion problem. If `synthesis.py` is created, it must be pure extraction with no behavior edits.

**Step 8: Verify and commit policy split**

Run:

```bash
uv run pytest tests/unit/rates/test_snapshot.py -q
uv run pytest tests/integration/api/test_openapi_snapshot.py -q
uv run ruff check src/uw_scan/rates/
git add src/uw_scan/rates/snapshot.py src/uw_scan/rates/policy.py
git commit -m "refactor: split rates policy snapshot builder"
```

---

## Task 5: Split Remaining Oversized UI Components

**Files:**
- Modify: `web/components/stock/panels/TradeInsightsAiAnalysisPanel.tsx`
- Create under: `web/components/stock/panels/tradeInsightsAi/`
- Modify: `web/components/rates/RatesDesk.tsx`
- Create under: `web/components/rates/sections/`
- Modify: `web/components/regime/GexSubTab.tsx`
- Create under: `web/components/regime/`
- Tests: existing web unit tests.

**Why:** These files remain close to 1,000 lines. The goal is reviewability and lower future change risk, not new behavior.

**Step 1: Split Trade Insights AI render sections**

Move render-only components from `TradeInsightsAiAnalysisPanel.tsx`:

- `AnalysisCard`
- `KeyValueGrid`
- `BulletList`
- `ScenarioList`
- `SectionSummaryCard`
- `OutcomeGrid`
- `ProviderTabBody`

into focused files under `web/components/stock/panels/tradeInsightsAi/`.

Keep exported `TradeInsightsAiAnalysisPanel` unchanged.

Do not move stateful polling logic in this task; `useAiAnalysisPolling.ts` is already the state boundary. Only move render-only components.

Before moving helpers, write a short dependency list in the PR notes for each moved component. Move formatting helpers only when the moved component directly needs them; put shared helpers in one local `format.ts` only when at least two moved files use the same helper.

**Step 2: Verify and commit Trade Insights AI UI split**

Run:

```bash
(cd web && npm run test -- tradeInsightsAiAnalysisPanel useAiAnalysisPolling tradeInsightsTab)
(cd web && npm run typecheck)
(cd web && npm run lint)
git add web/components/stock/panels/TradeInsightsAiAnalysisPanel.tsx web/components/stock/panels/tradeInsightsAi
git commit -m "refactor: split trade insights ai render sections"
```

After the commit, run a browser smoke for `http://127.0.0.1:3002/stock/TSLA/trade-insights` if the local API/dev server is running. If it is not running, record that the milestone has only automated test coverage and defer browser evidence to the final smoke.

**Step 3: Split RatesDesk remaining sections**

Move decomposition/curve/source freshness render helpers from `RatesDesk.tsx` into section components:

- `web/components/rates/sections/CurveSection.tsx`
- `web/components/rates/sections/DecompositionSection.tsx`
- `web/components/rates/sections/SourceFreshnessSection.tsx`

Keep `RatesDesk` as the page orchestrator.

Avoid moving shared formatting helpers into every section. If two or more sections need the same helper, create one `web/components/rates/format.ts` or keep the helper in `RatesDesk.tsx` until a third caller exists.

**Step 4: Verify and commit RatesDesk split**

Run:

```bash
(cd web && npm run test -- rates)
(cd web && npm run typecheck)
(cd web && npm run lint)
git add web/components/rates
git commit -m "refactor: split rates desk render sections"
```

After the commit, run a browser smoke for `http://127.0.0.1:3002/rates` if the local API/dev server is running.

**Step 5: Split GEX subtab**

Move:

- `MqLevelsPanel` to `web/components/regime/GexMqLevelsPanel.tsx`
- `GexHistoryTable` to `web/components/regime/GexHistoryTable.tsx`

Keep `GexSubTabView` as the tab orchestrator.

**Step 6: Verify and commit GEX split**

Run:

```bash
(cd web && npm run test -- regime)
(cd web && npm run typecheck)
(cd web && npm run lint)
git add web/components/regime
git commit -m "refactor: split gex subtab sections"
```

After the commit, run a browser smoke for `http://127.0.0.1:3002/regime` if the local API/dev server is running.

---

## Task 6: Cockpit Chart Render Cleanup

**Files:**
- Modify: `web/app/cockpit/[ticker]/CockpitChart.tsx`
- Modify callers as needed:
  - `web/app/cockpit/[ticker]/CockpitDealerTab.tsx`
  - `web/app/cockpit/[ticker]/CockpitVrpTab.tsx`
  - `web/app/cockpit/[ticker]/CockpitFlowImTab.tsx`
  - `web/app/cockpit/[ticker]/CockpitSurfaceTab.tsx`

**Why:** `MultiLineChart` normalizes, filters, sorts, flattens, and scales points during render. Most datasets are already chronological or strike-sorted by the caller.

**Step 1: Add a focused test if no cockpit chart test exists**

Search:

```bash
rg -n "MultiLineChart|CockpitChart" web/tests
```

If no test exists, add `web/tests/unit/cockpitChart.test.tsx` covering:

- unsorted input sorts by x by default
- `assumeSorted` preserves order
- null y values are dropped
- empty series renders `NO DATA`
- finite normalized data renders at least one polyline/path with valid numeric coordinates
- single-x or single-y input does not produce `NaN`/`Infinity` SVG coordinates

If a cockpit chart test already exists, extend it instead of adding a duplicate test file.

**Step 2: Extract normalization helper**

In `CockpitChart.tsx`, create:

```ts
export function normalizeChartSeries(
  series: ChartSeries[],
  assumeSorted = false,
): Array<{ label: string; color: string; points: Array<{ x: number; y: number }> }> {
  ...
}
```

Use it inside `MultiLineChart`.

**Step 3: Memoize normalized series**

Use `useMemo` in `MultiLineChart` keyed by `[series, assumeSorted]`. Do not mutate `series` or `points`.

If callers create fresh `series` arrays inline on every render, `useMemo` inside `MultiLineChart` will not help. Caller-side `series` construction must be memoized where the data inputs are stable; otherwise downgrade the commit from `perf:` to `refactor:` and limit this task to extracting/test-covering `normalizeChartSeries` plus marking verified sorted callers.

**Step 4: Mark sorted callers**

Set `assumeSorted` only where the caller demonstrably constructs points from DB-ordered ascending rows or already sorts by strike:

- Dealer vanna/charm already passes `assumeSorted`.
- Consider VRP/flow/surface only after verifying API order from repository query or caller sorting.

**Step 5: Verify**

Run:

```bash
(cd web && npm run test -- cockpit)
(cd web && npm run typecheck)
(cd web && npm run lint)
(cd web && npm run build)
```

Expected: all pass.

**Step 6: Commit**

Run:

```bash
git add web/app/cockpit web/tests/unit
git commit -m "perf: memoize cockpit chart normalization"
```

If caller-side `series` arrays could not be memoized and the task only extracted/test-covered normalization, use:

```bash
git commit -m "refactor: extract cockpit chart normalization"
```

---

## Final Verification

Run from the worktree root:

```bash
uv run ruff check src/ tests/ scripts/
uv run python scripts/_lint_except.py src
uv run python scripts/check_migration_prefixes.py
uv run pytest tests/unit/ -q
uv run pytest tests/integration/ -q
(cd web && npm run typecheck && npm run test && npm run lint && npm run build)
```

Expected: all pass.

## Browser Smoke

Start the app without conflicting with any existing 3001 instance:

```bash
cd /Users/chenxi/projects/unusual-whales/.worktrees/complexity-reduction-round-2

# Terminal A: start the API only, so the existing 3001 app is not disturbed.
uv run uvicorn uw_scan.api.server:app --host 127.0.0.1 --port 8400 --reload --reload-dir src

# Terminal B: verify API readiness before browser checks.
curl -fsS "http://127.0.0.1:8400/api/health?source=uw"

# Terminal B: start this worktree's web app on 3002.
cd web
NEXT_PUBLIC_API_BASE_URL=http://127.0.0.1:8400 NEXT_PUBLIC_API_BASE=http://127.0.0.1:8400 npx next dev --hostname 127.0.0.1 --port 3002
```

Then verify:

- `http://127.0.0.1:3002/rates`
- `http://127.0.0.1:3002/stock/TSLA/trade-insights`
- `http://127.0.0.1:3002/cockpit/SPX`
- `http://127.0.0.1:3002/regime`

Expected:

- HTTP 200
- rendered content is non-empty
- no Next runtime error overlay
- no console errors

## PR Checklist

Before opening PR:

```bash
git status --short
git log --oneline origin/main..HEAD
git diff --stat origin/main...HEAD
```

PR body must include:

- Summary by milestone.
- Runtime complexity changes for Tasks 1-3.
- Structural complexity changes for Tasks 4-6.
- Exact verification commands and pass/fail output.
- Browser smoke evidence.
