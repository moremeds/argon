# US Rates Mirror Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a live, persisted, 1:1-style US rates factor desk page based on the explored reference page, using real data sources instead of static pasted values.

**Architecture:** Ingest official rates/macro observations into Postgres, compute a durable `rates_snapshot` payload, expose it through FastAPI, then render a standalone Next.js `/rates` page that mirrors the reference page's sections, scorecard interaction, and visual tone. The UI must not fabricate stale reference-page values when live data are missing; it should show computed values, source freshness, and explicit gaps.

**Tech Stack:** Python 3.13 via `uv`, FastAPI, psycopg 3, APScheduler, Postgres `uw_scan`, Next.js 16/React 19, TypeScript, hand-rolled SVG charts, Vitest, Playwright.

---

## Ground Rules

- Work only in `/Users/chenxi/projects/unusual-whales/.claude/worktrees/feat+us-rates-mirror`.
- Do not commit unless the user explicitly asks. Commit steps below are checkpoint suggestions only.
- Keep migrations idempotent: `CREATE TABLE IF NOT EXISTS`, `CREATE INDEX IF NOT EXISTS`, `ON CONFLICT`.
- Persist derived rates analytics to Postgres; do not make the page a frontend-only live fetch or static data page.
- Do not append rates persistence methods to `src/uw_scan/storage/repository.py`; create a dedicated rates storage module.
- Do not leak `FRED_API_KEY`; telemetry must redact `api_key`, and scripts/logs must never print the key.
- Use the existing frontend API convention: `NEXT_PUBLIC_API_BASE_URL` and `web/lib/api.ts`. Do not introduce a second env var spelling.
- Use official/public data sources first. FRED is the main source but not enough for auctions, TIC, CFTC, FedWatch-style probabilities, or news.

## Reference Page Inventory

The target page at `https://us-treasury-bonds-monitor-luffa.vercel.app/#scorecard` has these user-visible sections:

- Sticky header with snapshot date and anchor navigation: Summary, Curve, Decomp, Scorecard, Policy, Supply, Positioning, Cross, Events, Synthesis.
- Summary KPI strip: 2Y, 5Y, 10Y, 30Y, 2s10s, 5s30s.
- Yield curve chart/table: tenors 1M, 3M, 6M, 1Y, 2Y, 3Y, 5Y, 7Y, 10Y, 20Y, 30Y; 1D/1W/1M deltas; slope and butterfly metrics.
- Decomposition: nominal 10Y, real yield, breakeven inflation, term/forward compensation, attribution windows.
- Scorecard: six editable weights, collapsible factor groups, factor scores from -2 to +2, composite duration score, curve score.
- Policy: target range, EFFR/SOFR, meeting path, balance sheet/plumbing cards.
- Supply: latest Treasury auctions and fiscal/QRA notes.
- Positioning: CFTC Treasury futures positioning and TIC foreign holdings.
- Cross-market: global 10Y yields, dollar/risk/credit, inflation/commodities.
- Events/news and investment synthesis.

Do not copy the reference source code verbatim. Rebuild the data contract and components in this repo's style while matching the information architecture and visual behavior.

## Data Source Plan

### FRED series for Phase 1

Use the FRED API with `FRED_API_KEY` for:

- Nominal Treasury curve: `DGS1MO`, `DGS3MO`, `DGS6MO`, `DGS1`, `DGS2`, `DGS3`, `DGS5`, `DGS7`, `DGS10`, `DGS20`, `DGS30`.
- TIPS real yields: `DFII5`, `DFII7`, `DFII10`, `DFII20`, `DFII30`.
- Breakevens/forwards: `T5YIE`, `T10YIE`, `T5YIFR`.
- Policy/reference rates: `EFFR`, `SOFR`, target range series after confirmation in implementation.
- Fed plumbing candidates: `WALCL`, `WRESBAL`, `RRPONTSYD`, `WTREGEN`, subject to confirmation by API response.
- Macro scorecard candidates: CPI/PPI/unemployment/payroll/growth proxies only when confirmed and documented in `RATES_SERIES`.

### Non-FRED official sources for later tasks

- Treasury auction results: Treasury FiscalData / auction dataset.
- TIC foreign holdings: Treasury TIC data.
- CFTC Treasury futures positioning: CFTC COT/TFF.
- Treasury QRA/fiscal notes: Treasury releases/FiscalData.
- Fed meeting probabilities: derive from fed funds futures only if a data source is available; otherwise mark unavailable rather than copying reference-page probabilities.
- News/events: official calendars and curated source metadata only.

Phase 1 can ship with live FRED-backed panels plus explicit "not yet wired" cards for non-FRED panels. Phase 2 wires the remaining official feeds.

---

## Task 1: Add FRED API Key Configuration

**Files:**
- Modify: `src/uw_scan/config.py`
- Modify: `.env.example`
- Test: `tests/unit/test_config.py` if present, otherwise create `tests/unit/test_settings_fred.py`

**Step 1: Write the failing test**

Create or extend a settings test that sets `FRED_API_KEY=abc123`, calls `Settings.from_env(env_path=tmp_env)`, and asserts:

```python
assert settings.api_key.get_secret_value() == "dummy-uw"
assert settings.fred_api_key is not None
assert settings.fred_api_key.get_secret_value() == "abc123"
```

Also test blank/unset `FRED_API_KEY` values produce `None`. The test env file must include `UW_SCAN_API_KEY=dummy-uw` because `Settings.from_env()` intentionally still requires the UW key for the application config.

**Step 2: Run test to verify it fails**

Run:

```bash
uv run pytest tests/unit/test_settings_fred.py -q
```

Expected: fail because `Settings` has no `fred_api_key`.

**Step 3: Implement minimal config support**

Add to `Settings`:

```python
fred_api_key: SecretStr | None = None
```

Add to `from_env`:

```python
fred_api_key=(
    SecretStr(_fred_key)
    if (_fred_key := os.environ.get("FRED_API_KEY", "").strip())
    else None
),
```

Add a blank placeholder to `.env.example`:

```dotenv
FRED_API_KEY=
```

**Step 4: Run tests**

Run:

```bash
uv run pytest tests/unit/test_settings_fred.py -q
```

Expected: pass.

**Checkpoint:** No commit unless explicitly requested.

---

## Task 2: Extend FRED Provider To Use Official JSON API

**Files:**
- Modify: `src/uw_scan/sources/fred.py`
- Test: `tests/unit/sources/test_fred_provider.py`

**Step 1: Write failing provider tests**

Cover:

- `fetch_observations_json("DGS10", start=...)` calls `/fred/series/observations`.
- Request params include `series_id`, `observation_start`, `file_type=json`, and `api_key`.
- Telemetry redacts `api_key`.
- JSON telemetry records `endpoint_key="fred_series_observations"` and `path_template="/fred/series/observations"`, not the legacy CSV endpoint values.
- Missing `"."` values are skipped.
- Parsed rows preserve `series_id`, `obs_date`, `value`, `realtime_start`, and `realtime_end`.

**Step 2: Run test to verify failure**

Run:

```bash
uv run pytest tests/unit/sources/test_fred_provider.py -q
```

Expected: fail because JSON API support does not exist.

**Step 3: Implement JSON support**

Keep CSV support for existing Gold jobs. Add:

```python
def fetch_observations(
    self,
    series_id: str,
    *,
    start: date | None = None,
    end: date | None = None,
) -> list[FredObservation]:
    ...
```

Constructor accepts:

```python
api_key: str | None = None
base_url: str = "https://api.stlouisfed.org"
```

If `api_key` is present, use `/fred/series/observations`; otherwise fall back to the current CSV endpoint. Keep the existing `fetch_series(...)` CSV behavior and `gold_fred_ingest_job` working unchanged.

Implementation detail:

- Keep CSV constants as `CSV_BASE_URL = "https://fred.stlouisfed.org"`, `CSV_ENDPOINT_PATH = "/graph/fredgraph.csv"`, and `CSV_ENDPOINT_KEY = "fred_csv"`.
- Add JSON constants as `API_BASE_URL = "https://api.stlouisfed.org"`, `API_ENDPOINT_PATH = "/fred/series/observations"`, and `API_ENDPOINT_KEY = "fred_series_observations"`.
- The constructor should not switch the provider's global base URL in a way that makes no-key CSV calls accidentally hit `api.stlouisfed.org/graph/fredgraph.csv`.
- Refactor telemetry helpers so each request passes its own `endpoint_key` and `path_template`; do not let JSON API requests be recorded as `fred_csv`.

**Step 4: Run tests**

Run:

```bash
uv run pytest tests/unit/sources/test_fred_provider.py tests/unit/test_settings_fred.py -q
```

Expected: pass.

---

## Task 3: Define Rates Domain Models And Series Catalog

**Files:**
- Create: `src/uw_scan/rates/__init__.py`
- Create: `src/uw_scan/rates/series.py`
- Create: `src/uw_scan/models/rates.py`
- Modify: `src/uw_scan/models/__init__.py`
- Test: `tests/unit/rates/test_series_catalog.py`

**Step 1: Write failing catalog/model tests**

Assert:

- Every yield-curve tenor has a FRED series ID.
- Response models import from `uw_scan.models` as stable public API.
- Duplicate series IDs are rejected by a helper or test.

**Step 2: Implement catalog**

Create constants:

```python
YIELD_CURVE_SERIES = {
    "1M": "DGS1MO",
    "3M": "DGS3MO",
    "6M": "DGS6MO",
    "1Y": "DGS1",
    "2Y": "DGS2",
    "3Y": "DGS3",
    "5Y": "DGS5",
    "7Y": "DGS7",
    "10Y": "DGS10",
    "20Y": "DGS20",
    "30Y": "DGS30",
}
```

Add `RATES_FRED_SERIES` as the de-duplicated fetch list for Phase 1.

**Step 3: Implement Pydantic response models**

Model the API around the page sections:

- `RatesSnapshotResponse`
- `RatesSummaryTile`
- `RatesCurvePoint`
- `RatesSlopeMetric`
- `RatesDecomposition`
- `RatesScorecardGroup`
- `RatesScorecardFactor`
- `RatesPolicyPanel`
- `RatesSupplyPanel`
- `RatesPositioningPanel`
- `RatesCrossMarketPanel`
- `RatesEventItem`
- `RatesSynthesisPanel`
- `RatesSourceFreshness`

Preserve module identity with `_preserve_public_module`, following `src/uw_scan/models/gold.py`.

**Step 4: Run tests**

Run:

```bash
uv run pytest tests/unit/rates/test_series_catalog.py -q
```

Expected: pass.

---

## Task 4: Add Rates Persistence

**Files:**
- Create: `src/uw_scan/storage/migrations/052_rates_tables.sql`
- Create: `src/uw_scan/storage/rates_repository.py`
- Modify: `src/uw_scan/storage/repository.py` to import and mix in `_RatesMixin`
- Test: `tests/integration/storage/test_rates_repository.py`

**Step 1: Write failing integration tests**

Use the repo's Postgres fixture pattern and assert:

- Upserting duplicate observations is idempotent across repeated ingest runs with different ingestion timestamps.
- Latest-vintage reads return one row per `(series_id, obs_date)`.
- Snapshot upsert stores and fetches latest JSON payload.
- A second snapshot for the same `snapshot_date` replaces the payload or creates a new `computed_at` version according to the chosen schema.
- Snapshot persistence accepts a payload containing `date`, `datetime`, and numeric values after JSON-mode model dumping.

**Step 2: Add migration**

Create:

```sql
CREATE TABLE IF NOT EXISTS uw_scan.rates_observations (
  series_id TEXT NOT NULL,
  obs_date DATE NOT NULL,
  value NUMERIC NOT NULL,
  realtime_start DATE NOT NULL,
  realtime_end DATE NOT NULL,
  first_seen_at TIMESTAMPTZ NOT NULL,
  last_seen_at TIMESTAMPTZ NOT NULL,
  release_date DATE NULL,
  source TEXT NOT NULL,
  source_url TEXT NULL,
  PRIMARY KEY (series_id, obs_date, realtime_start, realtime_end, source)
);

CREATE INDEX IF NOT EXISTS idx_rates_observations_lookup
  ON uw_scan.rates_observations (series_id, obs_date DESC, realtime_start DESC, last_seen_at DESC);

CREATE TABLE IF NOT EXISTS uw_scan.rates_snapshots (
  snapshot_date DATE NOT NULL,
  computed_at TIMESTAMPTZ NOT NULL,
  payload JSONB NOT NULL,
  source_freshness JSONB NOT NULL DEFAULT '[]'::jsonb,
  PRIMARY KEY (snapshot_date, computed_at)
);

CREATE INDEX IF NOT EXISTS idx_rates_snapshots_latest
  ON uw_scan.rates_snapshots (snapshot_date DESC, computed_at DESC);
```

**Step 3: Implement repository**

Methods:

- `upsert_rates_observation_rows(rows, *, seen_at, source) -> int`
- `fetch_rates_series(series_id, from_date=None, to_date=None) -> list[dict]`
- `fetch_latest_rates_values(series_ids, *, realtime_start_max=None) -> dict[str, dict]`
- `insert_rates_snapshot(snapshot_date, computed_at, payload, source_freshness) -> None`
- `fetch_latest_rates_snapshot() -> dict | None`

Use `Jsonb` for payloads after converting Pydantic models with `model_dump(mode="json")`. Keep SQL schema-qualified via `self._schema`.

Implementation detail:

- Define `class _RatesMixin:` in `src/uw_scan/storage/rates_repository.py`, matching the existing domain mixin pattern.
- Add `from .rates_repository import _RatesMixin` near the other storage mixin imports in `src/uw_scan/storage/repository.py`.
- Add `_RatesMixin` to the `Repository(...)` MRO before `_BaseMixin`.
- This is required because the API dependency returns `Repository`, and Task 8 calls `repo.fetch_latest_rates_snapshot()`.
- `upsert_rates_observation_rows` must use `ON CONFLICT (...) DO UPDATE SET value = EXCLUDED.value, last_seen_at = EXCLUDED.last_seen_at, release_date = EXCLUDED.release_date, source_url = EXCLUDED.source_url`; do not key unchanged observations by ingestion timestamp.

**Step 4: Run migration and tests**

Run:

```bash
bash scripts/migrate.sh
uv run pytest tests/integration/storage/test_rates_repository.py -q
```

Expected: pass.

---

## Task 5: Implement Rates Calculations

**Files:**
- Create: `src/uw_scan/rates/calculations.py`
- Test: `tests/unit/rates/test_calculations.py`

**Step 1: Write failing tests**

Use fixed sample observations to verify:

- Current curve points in percent.
- 1D/1W/1M deltas in basis points using latest available observation at or before target dates.
- Slopes: `2s10s`, `5s30s`, `3m10y`.
- Butterfly: `2s5s10s = 2 * 5Y - 2Y - 10Y` in basis points.
- Decomposition: 10Y nominal, 10Y real, 10Y breakeven, nominal-minus-real fallback when BEI missing.
- Finite/null safety when a series is missing.

**Step 2: Implement calculation helpers**

Add pure functions:

- `latest_on_or_before(points, target_date)`
- `delta_bps(current, prior)`
- `compute_curve(points_by_series)`
- `compute_slopes(curve_points)`
- `compute_decomposition(points_by_series)`
- `compute_source_freshness(points_by_series)`

**Step 3: Run tests**

Run:

```bash
uv run pytest tests/unit/rates/test_calculations.py -q
```

Expected: pass.

---

## Task 6: Build Snapshot Assembler And Scorecard Rules

**Files:**
- Create: `src/uw_scan/rates/scorecard.py`
- Create: `src/uw_scan/rates/snapshot.py`
- Test: `tests/unit/rates/test_scorecard.py`
- Test: `tests/unit/rates/test_snapshot.py`

**Step 1: Write failing tests**

Assert:

- Default weights are `25,25,15,15,10,10`.
- Group score is the arithmetic average of factor scores in that group.
- Composite duration score is the weighted average of group scores divided by total active weight.
- Curve score defaults to live curve logic, not hard-coded reference values.
- Snapshot payload includes every top-level section even when some source groups are unavailable.

**Step 2: Implement scorecard rules**

Create deterministic factor groups matching the reference layout:

- Monetary Policy
- Macro Fundamentals
- Supply & Technicals
- Demand & Positioning
- Relative Value
- Sentiment & Liquidity

Phase 1 factor values must be computed only from available live data. For not-yet-wired official feeds, set factor `status="missing"` and exclude or neutralize by documented rule. Do not paste the reference page's stale score values.

**Step 3: Implement snapshot assembler**

Function:

```python
def build_rates_snapshot(observations: dict[str, list[dict]]) -> RatesSnapshotResponse:
    ...
```

It should populate:

- `as_of`
- `summary`
- `curve`
- `decomposition`
- `scorecard`
- `policy`
- `supply`
- `positioning`
- `cross_market`
- `events`
- `synthesis`
- `source_freshness`

**Step 4: Run tests**

Run:

```bash
uv run pytest tests/unit/rates/test_scorecard.py tests/unit/rates/test_snapshot.py -q
```

Expected: pass.

---

## Task 7: Add Rates Ingest And Compute Worker Job

**Files:**
- Create: `src/uw_scan/worker/jobs/rates_jobs.py`
- Modify: `src/uw_scan/worker/scheduler.py`
- Test: `tests/unit/worker/test_rates_jobs.py`
- Test: `tests/unit/worker/test_scheduler_rates.py` if scheduler job registration has existing tests; otherwise keep to job tests.

**Step 1: Write failing job tests**

Use fake FRED provider/repo objects. Assert:

- Job fetches every `RATES_FRED_SERIES`.
- Job receives the unwrapped FRED key from scheduler/settings and passes it to `FredProvider`.
- Job fails fast with a clear `RuntimeError` when `fred_api_key` is missing; CSV fallback is allowed only for the existing Gold `fetch_series(...)` path, not for the rates ingest.
- Job passes a telemetry hook/recorder to `FredProvider`, and tests assert `api_key` is absent from recorded params.
- Job telemetry is attributed to `job_name="rates_fred_ingest"`.
- Observations are persisted before snapshot computation.
- Snapshot is persisted.
- Job returns a result object containing `inserted_observations`, `failed_series`, `snapshot_date`, and `computed_at`.
- Per-series failures are logged and do not abort all other series.

**Step 2: Implement job**

Add:

```python
def rates_fred_ingest_job(
    *,
    dsn: str,
    fred_api_key: str | None,
    lookback_days: int = 45,
    record_request: RecordHook | None = None,
) -> RatesIngestResult:
    ...
```

Use `FredProvider(api_key=fred_api_key, record_request=record_request, job_name="rates_fred_ingest")` and `Repository`/`_RatesMixin`.

**Step 3: Register scheduler**

In `src/uw_scan/worker/scheduler.py`, add a primary-worker job after H.15 is normally available. Wrap it with `_external_api_recorder(settings)` so FRED request telemetry is persisted like the other external providers:

```python
def _rates_fred_ingest() -> None:
    if settings.fred_api_key is None:
        logger.warning("FRED_API_KEY not set; skipping rates_fred_ingest")
        return
    with _external_api_recorder(settings) as recorder:
        rates_fred_ingest_job(
            dsn=settings.db_dsn(),
            fred_api_key=settings.fred_api_key.get_secret_value(),
            record_request=lambda _provider, event: recorder.record(event),
        )

sched.add_job(
    _rates_fred_ingest,
    CronTrigger.from_crontab("45 18 * * 0-4", timezone=settings.rth_tz),
    id="rates_fred_ingest",
    name="Rates: FRED curve and macro refresh",
)
```

The `18:45 ET` slot avoids the existing Gold ETF holdings job at `18:30 ET` and leaves room after H.15 publication. If this later conflicts, choose the nearest non-conflicting ET time and document it in code.

**Step 4: Run tests**

Run:

```bash
uv run pytest tests/unit/worker/test_rates_jobs.py -q
```

Expected: pass.

---

## Task 8: Add FastAPI Rates Router

**Files:**
- Create: `src/uw_scan/api/routers/rates.py`
- Modify: `src/uw_scan/api/server.py`
- Modify: `web/lib/api.ts`
- Regenerate: `web/lib/types.ts`
- Regenerate: `tests/integration/api/openapi.snapshot.json`
- Test: `tests/integration/api/test_rates_router.py`
- Test: existing OpenAPI snapshot test, or add/extend `tests/integration/api/test_openapi_snapshot.py` if this branch requires an explicit test target

**Step 1: Write failing API tests**

Assert:

- `GET /api/rates/snapshot` returns latest persisted snapshot.
- Empty DB returns 404 or a typed empty response. Prefer 404 if no snapshot has ever been computed.
- Response validates as `RatesSnapshotResponse`.

**Step 2: Implement router**

Add:

```python
router = APIRouter(prefix="/rates", tags=["rates"])

@router.get("/snapshot", response_model=RatesSnapshotResponse)
def rates_snapshot(repo: Repository = Depends(get_repo)) -> RatesSnapshotResponse:
    row = repo.fetch_latest_rates_snapshot()
    if row is None:
        raise HTTPException(status_code=404, detail="rates snapshot not computed")
    return RatesSnapshotResponse.model_validate(row["payload"])
```

Wire it in `create_app()`.

**Step 3: Regenerate OpenAPI types**

Run API locally, then:

```bash
cd web && npm run gen:types
```

**Step 4: Add web API helper**

In `web/lib/api.ts`, add `type RatesSnapshotResponse = Json<"/api/rates/snapshot", "get">;` and `api.ratesSnapshot()`. This keeps the base URL as `process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8400"`.

`api.ratesSnapshot()` must return `null` only for 404 by using the existing `allow404` convention. Non-404 errors must still throw so backend/schema regressions do not render as an empty rates page.

**Step 5: Run tests**

Run:

```bash
uv run pytest tests/integration/api/test_rates_router.py -q
uv run pytest tests/integration/api/test_openapi_snapshot.py -q
```

Expected: pass.

---

## Task 9: Create Standalone `/rates` Shell

**Files:**
- Create: `web/components/shared/AppShell.tsx`
- Modify: `web/app/layout.tsx`
- Test: `web/tests/unit/AppShell.test.tsx`

**Step 1: Write failing web test**

Assert:

- Normal routes render the sidebar.
- `/rates` does not render the Argon sidebar and allows full viewport width.
- `/rates` gets its own scrollable viewport despite the root `body { overflow: hidden }`.

**Step 2: Implement shell split**

Because `RootLayout` is a server component and path detection is client-side, create a small client shell:

```tsx
"use client";

import { usePathname } from "next/navigation";
import { Sidebar } from "@/components/shared/Sidebar";

export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const isStandalone = pathname === "/rates" || pathname.startsWith("/rates/");
  if (isStandalone) {
    return (
      <main style={{ height: "100vh", overflowY: "auto", background: "#f4f3fd" }}>
        {children}
      </main>
    );
  }
  return (
    <div style={{ display: "flex", height: "100vh" }}>
      <Sidebar />
      <main style={{ flex: 1, minWidth: 0, height: "100vh", overflowY: "auto" }}>
        {children}
      </main>
    </div>
  );
}
```

Use `<AppShell>{children}</AppShell>` in `web/app/layout.tsx`.

If the light rates page needs to avoid Argon dark-theme globals from `<html data-theme="dark">`, handle that in scoped rates CSS and verify the rendered page colors in Playwright. Do not mutate the root theme globally for other routes.

**Step 3: Run tests**

Run:

```bash
cd web && npm run test -- AppShell
```

Expected: pass.

---

## Task 10: Build `/rates` Page And Mirror Components

**Files:**
- Create: `web/app/rates/page.tsx`
- Create: `web/app/rates/error.tsx`
- Create: `web/app/rates/loading.tsx`
- Create: `web/components/rates/RatesDesk.tsx`
- Create: `web/components/rates/RatesCurveChart.tsx`
- Create: `web/components/rates/RatesScorecard.tsx`
- Create: `web/components/rates/RatesSection.tsx`
- Create: `web/components/rates/ratesStyles.ts` or `web/components/rates/RatesDesk.module.css`
- Test: `web/tests/unit/rates/RatesScorecard.test.tsx`
- Test: `web/tests/unit/rates/RatesDesk.test.tsx`

**Step 1: Write failing component tests**

Assert:

- Header/nav renders all 10 anchors.
- KPI strip renders 2Y, 5Y, 10Y, 30Y, 2s10s, 5s30s from props.
- Curve table renders all 11 tenors.
- Scorecard weight changes recalculate composite score client-side.
- Collapsible scorecard groups open/close.
- Missing source cards render as unavailable, not as fake static data.
- Non-404 API errors render an explicit error state via `web/app/rates/error.tsx` instead of being swallowed as `null`.
- Numeric chart/score fields render correctly when the generated OpenAPI type supplies numbers as strings.

**Step 2: Implement RSC page fetch**

`web/app/rates/page.tsx` should use the typed API helper instead of inlining a second base URL:

```tsx
import { RatesDesk } from "@/components/rates/RatesDesk";
import { api } from "@/lib/api";

export default async function RatesPage() {
  const snapshot = await api.ratesSnapshot();
  return <RatesDesk snapshot={snapshot} />;
}

export const metadata = { title: "US Rates Factor Desk" };
export const dynamic = "force-dynamic";
```

**Step 3: Implement visual mirror**

Match the explored reference:

- Light page background around `#f4f3fd`.
- White panels with soft shadow.
- Orange accent around `#ff7a5c`.
- Bull green / bear pink score colors.
- `Plus Jakarta Sans`-like sans font fallback and mono numeric styling.
- Sticky header and anchor nav.
- Dense analytical page, not a marketing page.

Use existing dependencies only unless absolutely needed. Hand-roll the SVG curve chart.

**Step 4: Implement interactive scorecard**

Client component behavior:

- Six numeric weight inputs.
- Group collapse/expand.
- Recompute composite score and duration stance immediately.
- Preserve initial server-computed values.
- Do not persist edited weights in Phase 1 unless the user asks.
- Normalize numeric props with a small helper such as `toFiniteNumber(value, fallback)` before chart domains and scorecard math. Pydantic `Decimal` fields can arrive in generated TypeScript types as strings.

**Step 5: Run web tests**

Run:

```bash
cd web && npm run test -- rates
```

Expected: pass.

Note: baseline `npm run test` currently fails on unrelated Greek chart dropdown tests. Do not claim full web suite is green until those are fixed or explicitly excluded.

---

## Task 11: Add First Live Snapshot Backfill Command

**Files:**
- Create: `scripts/rates_backfill_once.py`
- Test: `tests/unit/test_rates_backfill_script.py` if script parsing is testable; otherwise validate with a dry run command.

**Step 1: Implement CLI**

Add a small operator script:

```bash
uv run python scripts/rates_backfill_once.py --lookback-days 90
```

Behavior:

- Load `Settings.from_env()`.
- Use `rates_fred_ingest_job`.
- Require both `UW_SCAN_API_KEY` and `FRED_API_KEY` through `Settings.from_env()`; this script is app-config based, not a rates-only config path.
- Print inserted row count, failed series count/list, latest snapshot date, and computed timestamp from the job result.
- Never print the FRED key or UW key.
- Exit non-zero when no snapshot can be built after ingest, so automation does not silently serve an empty page.

**Step 2: Run local backfill**

Run:

```bash
bash scripts/migrate.sh
uv run python scripts/rates_backfill_once.py --lookback-days 90
```

Expected: rates observations and one snapshot row are persisted.

---

## Task 12: Browser Verification With Playwright

**Files:**
- Create/update Playwright test if the repo has an obvious e2e layout: `web/tests/e2e/rates.spec.ts`
- Artifact: screenshot under `output/playwright/` if using local helper scripts

**Step 1: Start local stack**

Run from the worktree:

```bash
bash scripts/dev.sh
```

If port `3001` is busy, use the repo's normal port override for the web command and keep FastAPI on `8400`.

**Step 2: Verify API**

Run:

```bash
curl -s http://127.0.0.1:8400/api/rates/snapshot | jq '.as_of, .curve.points | length'
```

Expected: valid date and `11`.

**Step 3: Verify UI**

Use Playwright to open:

```text
http://127.0.0.1:3001/rates#scorecard
```

Check:

- No Argon sidebar.
- Header/nav visible.
- Scorecard anchor lands on the scorecard.
- Curve SVG is nonblank.
- Weight edits change composite score.
- Full page scroll works on `/rates` despite the root layout's hidden body overflow.
- Mobile viewport has no overlapping text.

**Step 4: Save screenshots**

Save desktop and mobile screenshots:

- `output/playwright/rates-page-desktop.png`
- `output/playwright/rates-page-mobile.png`

---

## Task 13: Final Verification

Run:

```bash
uv run pytest tests/unit/rates tests/unit/sources/test_fred_provider.py tests/unit/worker/test_rates_jobs.py -q
uv run pytest tests/integration/storage/test_rates_repository.py tests/integration/api/test_rates_router.py tests/integration/api/test_openapi_snapshot.py -q
cd web && npm run typecheck
cd web && npm run test -- rates AppShell
cd web && npm run build
```

Then run targeted Playwright verification from Task 12.

Record known baseline issues separately:

- `cd web && npm run test` currently fails on unrelated Greek chart expiry dropdown/select tests in the fresh `origin/main` worktree.
- Full `uv run pytest` may require a fully available local Postgres integration setup; unit baseline passed with `424 passed`.

---

## Phase 2 Follow-Up: Complete Non-FRED Feeds

After the FRED-backed mirror is functional, add separate source modules and persistence for:

- Treasury FiscalData auctions.
- CFTC COT/TFF Treasury futures positioning.
- Treasury TIC foreign holdings.
- QRA/fiscal source parser.
- Fed funds futures path if a reliable data source is available.
- Events/news source curation.

Each source should have its own provider tests, idempotent persistence, and source freshness in the rates snapshot.

---

## Final Self Review

**Review date:** 2026-05-21

**Verdict:** Ready to execute after patches.

**Assumptions verified:**

- Worktree is isolated on `feat/us-rates-mirror`; only this plan file is untracked.
- `.env` exists in the worktree and contains `FRED_API_KEY`; the key was not printed during verification.
- `.env.example` exists and is the right file for adding a blank `FRED_API_KEY=` placeholder.
- `web/lib/api.ts` uses `NEXT_PUBLIC_API_BASE_URL` and already has an `allow404` fetch convention.
- `tests/integration/api/test_openapi_snapshot.py` and `tests/integration/api/openapi.snapshot.json` exist, so OpenAPI snapshot regeneration is a real required step.
- `web/tests/unit` and `web/tests/e2e` exist, matching the planned component and Playwright test locations.
- Live FRED API verification succeeded for all Phase 1 candidate series: `DGS1MO`, `DGS3MO`, `DGS6MO`, `DGS1`, `DGS2`, `DGS3`, `DGS5`, `DGS7`, `DGS10`, `DGS20`, `DGS30`, `DFII5`, `DFII7`, `DFII10`, `DFII20`, `DFII30`, `T5YIE`, `T10YIE`, `T5YIFR`, `EFFR`, `SOFR`, `WALCL`, `WRESBAL`, `RRPONTSYD`, `WTREGEN`.
- Live FRED observations verification for `DGS10` returned `date`, `realtime_start`, `realtime_end`, and `value`, matching the revised vintage-aware schema.

**Issues found and patched during review:**

- Added dummy `UW_SCAN_API_KEY` requirement to settings tests because `Settings.from_env()` hard-fails without it.
- Made rates ingest fail fast without `FRED_API_KEY`; CSV fallback stays limited to the existing Gold FRED path.
- Required FRED JSON telemetry to use the JSON endpoint key/path and redact `api_key`.
- Replaced ingestion-time primary keying with FRED realtime vintage keying to avoid duplicate rows on each run.
- Required snapshot payloads to be persisted with JSON-native Pydantic dumps.
- Required API helper behavior to swallow only 404 and surface non-404 failures.
- Added OpenAPI snapshot regeneration/test coverage.
- Added standalone `/rates` scroll verification because the root layout uses hidden body overflow.
- Added numeric normalization for generated TypeScript payloads that may represent Decimal fields as strings.
- Changed latest-value repository filtering from stale `as_of_max` naming to `realtime_start_max`.
