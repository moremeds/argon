# Regime Port from xenon — Implementation Plan (LONG-TERM ROADMAP)

> **⚠️ This is the LONG-TERM roadmap, NOT the executable plan for this iteration.**
>
> The executable plan is **`2026-05-16-regime-gex-first.md`** — it ships `/regime` with GEX live (UW-driven) and CRI/VCG as "pending" placeholders, deferring backend work for CRI/VCG until the IB-via-R2 reader is wired (separate project, currently flaky).
>
> This file remains useful as the **full-fidelity reference** for when CRI/VCG land:
> - Pydantic schema shapes for CRI and VCG (Task 2)
> - Repository method signatures for `fetch_latest_cri`, `fetch_cri_history`, `fetch_latest_vcg` (Task 3)
> - FastAPI router shape for the full CRI/VCG endpoints (Task 4)
> - CRI sub-tab visual port spec — `RegimeStrip`, `RegimeRelationshipView`, `CriHistoryChart` (Tasks 7-8)
> - VCG sub-tab visual port spec (Task 9)
> - The 3-round review history (Round 1 self-review, Round 2 codex tribunal, Round 3 self-review w/ patches) is preserved for future re-execution context.
>
> When the IB-via-R2 reader lands, the follow-up plan should:
> 1. Add `src/uw_scan/sources/r2_ib.py` — reads VIX/VVIX/COR1M/SPY parquet from R2 via boto3 with R2 endpoint
> 2. Port the CRI and VCG scanners (math only, no IB code), reading from R2 + UW
> 3. Cherry-pick the CRI/VCG frontend work specified below
>
> ---

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Review history (latest first):**
- 2026-05-16 Round 3 (Claude self-review + codex-review tribunal, bilateral mode after Gemini sandbox-blocked):
  - 🔴 Replaced fabricated `get_db_connection` with real `get_repo` from `src/uw_scan/api/deps.py`
  - 🔴 Pydantic models moved from invented `src/uw_scan/api/models/regime.py` into existing `src/uw_scan/api/schemas.py`; full xenon field set ported (VcgSignal + attribution, GexData with profile/bias/iv/mq/source_delta — 18+ extra fields)
  - 🔴 Repository methods on existing `Repository` class (CLAUDE.md "one method per query") — dropped standalone `regime_repository.py` module
  - 🔴 Frontend hooks now use `process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8400"` via new `web/lib/regime/api.ts` wrapper (bare `/api/regime` was hitting Next.js port 3001)
  - 🔴 Ported `useSyncHook` (236 LOC) so hooks return `UseSyncReturn<T>` with `{loading, syncing, syncNow, ...}` — copied VcgPanel/GexPanel destructure these
  - 🔴 Added `d3` + `@types/d3` install + ported `charts/ChartPanel` and `charts/ChartLegend` wrappers (user-approved deviation from "no chart library" rule for 1:1 mirror)
  - 🟡 Pydantic validators replicate xenon's `normalizeCriPayload` (numeric-string coercion, bad-level fallback to LOW, filter non-numeric `spy_closes`)
  - 🟡 Migration extended to mirror xenon's full computed-column set (~20 more across VCG + GEX): attribution_*, ro, edr, tier, bounce, vvix_severity, sign_ok, level_*_strike/gamma
  - 🟡 Test fixtures fixed: integration tests use `seeded_db_empty_cards: Repository` + `client: TestClient` (fabricated `pg_conn` removed)
  - 🟡 Task 5 fixed: keep API running between Task 4 and Task 5 (gen:types fetches from localhost:8400)
  - 🟡 CSS extraction now uses a brace-balanced parser that preserves `@media` boundaries
  - 🟡 Sync Now button KEPT in CRI empty state — wired to POST /api/regime/scan (1:1 visual fidelity)
  - 🟢 Sidebar nav target: `web/components/shared/Sidebar.tsx` (NAV array). Was incorrectly Header.tsx.
  - 🟢 GEX default ticker is `SPX` everywhere (was inconsistent SPY/SPX)
  - 🟢 `chartSeriesColor` is string-keyed (`"caution"`, `"dislocation"`); numeric-index fallback removed
  - 🟢 Task 8 duplicate compile/commit step blocks merged
- 2026-05-16 Round 1 (Claude self-review): added RegimeStrip, RegimeRelationshipView, useMarketHours, pricesProtocol, VCG/GEX scan stubs, market_open runtime override; clarified d3 + scope deviations.
- 2026-05-16 Initial draft.

**Goal:** Port xenon's `/regime` top-level page and its three sub-tabs (CRI / VCG / GEX) into unusual-whales as a 1:1 visual + structural mirror. Data sources stay stubbed (empty payloads) until a separate backfill phase.

**Architecture:**
- **DB**: Three new `uw_scan.*` tables (`cri_series`, `vcg_series`, `gex_snapshots`) mirroring xenon's full JSONB-payload-with-computed-columns shape (`src/xenon/db/schema.py:458-642`). Every generated column xenon exposes (~40 across the 3 tables) is replicated so future analytics queries are field-compatible. Idempotent SQL migration.
- **Backend**: New `regime` FastAPI router under `src/uw_scan/api/routers/regime.py` exposing `GET /api/regime` + `POST /api/regime/scan` (CRI), `GET /api/regime/vcg` + `POST /api/regime/vcg/scan`, `GET /api/regime/gex` + `POST /api/regime/gex/scan`. Each GET reads the latest row via Repository methods; with empty tables they return the same `EMPTY_*` shape xenon's Next.js route uses for upstream-down fallback. POST `/scan` endpoints are 202 stubs until backfill phase.
  - **URL adaptation**: xenon FastAPI mounts these at `/regime`, `/vcg`, `/gex` (top-level). This repo's convention is `prefix="/api"` for every router (`server.py:34-42`), so we mount at `/api/regime/*`. The frontend fetches via the existing `API` constant in `web/lib/api.ts:3` — `process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8400"` — NOT bare `/api/...` paths (which would hit Next.js port 3001).
  - **Pydantic location**: Response shapes extend `src/uw_scan/api/schemas.py` (the existing API-contract file with docstring "Pydantic response models — over-the-wire contract"). **No new `api/models/` directory** — that's not this repo's pattern.
  - **Repository pattern**: Per CLAUDE.md "one method per query", new methods (`fetch_latest_cri`, `fetch_cri_history`, `fetch_latest_vcg`, `fetch_latest_gex`) live on the existing `Repository` class at `src/uw_scan/storage/repository.py:579`. **No standalone `regime_repository.py` module** — violates the convention.
  - **DI pattern**: Routers use `Annotated[Repository, Depends(get_repo)]` from `src/uw_scan/api/deps.py`. **`get_db_connection` does NOT exist** — never reference it.
  - **Shape normalization**: xenon's Next.js `normalizeCriPayload` (`route.ts:55-114` — coerces strings to numbers, filters bad arrays, backfills realized vol, fallback bad CRI levels to LOW) moves into Pydantic v2 `field_validator`s on `CriResponse`. Equivalent semantics, validated at the FastAPI boundary instead of Next.js.
  - **market_open runtime override**: xenon `route.ts:198-201` overrides stored `market_open` with current ET clock. Replicated in the router's GET handler via `_is_market_open_now()`.
- **Frontend**: New `web/app/regime/page.tsx` + `web/components/regime/*` mirroring xenon's `RegimePanel` and **all visual sub-components** rendered inside the CRI tab — `RegimeStrip` + cells (`RegimePanel.tsx:354-407`) and `RegimeRelationshipView` (693 LOC, `RegimePanel.tsx:507`).
  - **d3 dependency** (deviation from CLAUDE.md "no chart library" — user-approved 2026-05-16 for 1:1 visual mirror). `CriHistoryChart` and `RegimeRelationshipView` both import `* as d3 from "d3"` (xenon source lines 4 of each). Trying to rewrite as hand-rolled SVG is ~1000 LOC of work and loses visual fidelity. The plan installs `d3` + `@types/d3` and ports the two chart wrappers (`charts/ChartPanel.tsx`, `charts/ChartLegend.tsx`, 96 LOC). Document this deviation in the PR description.
  - **Hook contract**: xenon hooks all return `UseSyncReturn<T>` (`{data, loading, syncing, syncNow, lastSync, ...}`) and accept a `marketState` arg — see `lib/useSyncHook.ts`. Port `useSyncHook` so the copied VcgPanel/GexPanel destructure `loading` / `syncNow` without rewriting them. Ported hooks call through to `web/lib/regime/api.ts` which wraps the existing `API` constant from `web/lib/api.ts`.
  - **Ported but degraded** (no live data source yet): strip's `LiveBadge`s read CACHED; `MarketState` reports CLOSED outside ET market hours via the ported `useMarketHours`. `prices={}` empty map for live overlays.
  - **Empty state Sync Now button**: kept (1:1 visual). Wires to POST `/api/regime/scan` which returns the 202 stub; UI shows the returned `message: "scanner_pending: ..."` as a toast.
  - **Stripped (xenon-only)**: `ShareReportModal` + X share routes (`/regime/share`, `/vcg/share`, `/gex/share`), `xenonFetch`, account scope guards, IB-specific scanner subprocess hooks.
- **Out of scope (this plan)**: Scanner internals (`cri.py` / `vcg.py` / `gex.py` ≈ 3700 LOC), share-to-X social posting + its FastAPI routes, `regime_overrides` table (governance gate, unrelated to the 3 sub-tabs), Cboe / FMP / IB data source wiring, holiday-aware market hours.

**Tech Stack:** Python 3.13 / FastAPI / psycopg / Pydantic v2 (backend) — Next.js 16 / React 19 / TypeScript / hand-rolled SVG charts (frontend) — pytest / Vitest / Playwright.

---

## File Structure

**Create:**
- `src/uw_scan/storage/migrations/037_regime_tables.sql` — schema for cri_series, vcg_series, gex_snapshots (with FULL generated-column set from xenon)
- `src/uw_scan/api/routers/regime.py` — FastAPI router with 6 endpoints (3 GET, 3 POST stubs)
- `tests/integration/api/test_regime_router.py` — API shape + empty-state tests (uses `client: TestClient` fixture)

**Modify (extend existing files, do NOT create new dirs):**
- `src/uw_scan/api/schemas.py` — append regime response models (`CriResponse`, `VcgResponse`, `GexResponse` + sub-models + validators)
- `src/uw_scan/storage/repository.py` — append methods to `Repository` class: `fetch_latest_cri`, `fetch_cri_history`, `fetch_latest_vcg`, `fetch_latest_gex`
- `src/uw_scan/api/server.py` — register router (line 42-ish, after `trade_insights.router`)
- `web/components/shared/Sidebar.tsx` — append `{ href: "/regime", label: "Regime", icon: ... }` to the `NAV` array
- `web/app/globals.css` — append regime-specific styles (with `@media` boundaries preserved)
- `web/package.json` — add `d3` + `@types/d3` to dependencies (user-approved deviation from "no chart library" rule for 1:1 mirror)

**Frontend files (new):**
- `web/app/regime/page.tsx` — top-level page route
- `web/components/regime/RegimePanel.tsx` — main panel with 3 sub-tab nav
- `web/components/regime/CriSubTab.tsx` — CRI hero + components + history
- `web/components/regime/VcgSubTab.tsx` — VCG signal panel
- `web/components/regime/GexSubTab.tsx` — GEX profile + levels panel
- `web/components/regime/CriHistoryChart.tsx` — 20-session VIX/VVIX/RVOL/COR1M chart (346 LOC port; uses d3)
- `web/components/regime/GexProfileChart.tsx` — gamma profile by strike (port; uses d3)
- `web/components/regime/RegimeStrip.tsx` — top status strip + named exports `LiveBadge` / `DayChange` / `PointChange` / `RegimeStripCell` (79 LOC port)
- `web/components/regime/RegimeRelationshipView.tsx` — VIX/COR1M scatter + history (693 LOC port; uses d3)
- `web/components/regime/charts/ChartPanel.tsx` — d3-aware chart container (69 LOC port)
- `web/components/regime/charts/ChartLegend.tsx` — shared chart legend (27 LOC port)
- `web/components/regime/InfoTooltip.tsx` — shared tooltip (95 LOC port if not already present)
- `web/components/regime/ui/MetricCard.tsx` — `MetricCard` + `SourceBadge` named exports (87 LOC port)
- `web/lib/regime/api.ts` — typed regime API wrapper consuming the shared `API` constant from `web/lib/api.ts:3` (`process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8400"`)
- `web/lib/regime/useSyncHook.ts` — generic `useSyncHook<T>(endpoint, opts): UseSyncReturn<T>` (port from `xenon/web/lib/useSyncHook.ts`)
- `web/lib/regime/useRegime.ts` — `useRegime(marketState, opts): UseSyncReturn<CriData>`
- `web/lib/regime/useVcg.ts` — `useVcg(marketState): UseSyncReturn<VcgData>`
- `web/lib/regime/useGex.ts` — `useGex(marketState, ticker?): UseSyncReturn<GexData>` (default ticker `"SPX"`)
- `web/lib/regime/useMarketHours.ts` — `MarketState` enum + ET-clock hook (81 LOC port)
- `web/lib/regime/pricesProtocol.ts` — `PriceData` type (207 LOC port for type surface)
- `web/lib/regime/regimeLiveStrip.ts` — `resolveRegimeStripLiveState` (97 LOC port)
- `web/lib/regime/regimeRelationships.ts` — model behind `RegimeRelationshipView` (174 LOC port)
- `web/lib/regime/criCalc.ts` — `computeCri` + `CriLevel` + `CriResult` (103 LOC port)
- `web/lib/regime/criStaleness.ts` — `isCriDataStale` (57 LOC port)
- `web/lib/regime/regimeHistory.ts` — `backfillRealizedVolHistory` (66 LOC port)
- `web/lib/regime/sectionTooltips.ts` — `SECTION_TOOLTIPS` for CRI/VCG/GEX keys only (subset of xenon's 151 LOC)
- `web/lib/regime/chartSystem.ts` — `chartSeriesColor(name: string)` + named-token map (subset of xenon's 48 LOC; **string-keyed, NOT index-based**)
- `web/lib/regime/types.ts` — re-exports under stable names: `CriData`, `VcgData`, `VcgSignal`, `VcgHistoryEntry`, `GexData`, `GexLevel`, `GexBucket`, `GexBias`, `GexHistoryEntry`, `MqLevels`, `SourceDelta`, `IvData`
- `web/tests/unit/regime-page.test.ts` — Vitest: page renders + tabs swap + empty state
- `web/tests/e2e/regime-page.spec.ts` — Playwright: smoke test for /regime route

---

## Task 1: DB schema migration

**Files:**
- Create: `src/uw_scan/storage/migrations/037_regime_tables.sql`

- [ ] **Step 1: Write migration SQL**

```sql
-- 037_regime_tables.sql
--
-- Mirror xenon's regime persistence: three append-only series tables, JSONB
-- payloads with computed columns for indexable scalars. Idempotent (IF NOT
-- EXISTS). Tables stay empty until backfill phase wires data sources.

BEGIN;

-- ── CRI series: market-wide crash risk indicator snapshots ──────────────
CREATE TABLE IF NOT EXISTS uw_scan.cri_series (
    id              BIGSERIAL PRIMARY KEY,
    cri_level       NUMERIC(8,4) NOT NULL,
    alert           BOOLEAN NOT NULL DEFAULT FALSE,
    payload         JSONB,
    recorded_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    recorded_date   DATE GENERATED ALWAYS AS (
        CASE WHEN payload->>'date' ~ '^\d{4}-\d{2}-\d{2}$'
             THEN make_date(
                 split_part(payload->>'date','-',1)::int,
                 split_part(payload->>'date','-',2)::int,
                 split_part(payload->>'date','-',3)::int)
        END
    ) STORED,
    vix             NUMERIC(8,4)  GENERATED ALWAYS AS ((payload->>'vix')::numeric) STORED,
    vvix            NUMERIC(8,4)  GENERATED ALWAYS AS ((payload->>'vvix')::numeric) STORED,
    spy             NUMERIC(10,4) GENERATED ALWAYS AS ((payload->>'spy')::numeric) STORED,
    vix_5d_roc      NUMERIC(8,4)  GENERATED ALWAYS AS ((payload->>'vix_5d_roc')::numeric) STORED,
    vvix_vix_ratio  NUMERIC(8,4)  GENERATED ALWAYS AS ((payload->>'vvix_vix_ratio')::numeric) STORED,
    spx_100d_ma     NUMERIC(10,4) GENERATED ALWAYS AS ((payload->>'spx_100d_ma')::numeric) STORED,
    spx_distance_pct NUMERIC(8,4) GENERATED ALWAYS AS ((payload->>'spx_distance_pct')::numeric) STORED,
    cor1m           NUMERIC(6,4)  GENERATED ALWAYS AS ((payload->>'cor1m')::numeric) STORED,
    cor1m_previous_close NUMERIC(6,4) GENERATED ALWAYS AS ((payload->>'cor1m_previous_close')::numeric) STORED,
    cor1m_5d_change NUMERIC(6,4)  GENERATED ALWAYS AS ((payload->>'cor1m_5d_change')::numeric) STORED,
    realized_vol    NUMERIC(8,4)  GENERATED ALWAYS AS ((payload->>'realized_vol')::numeric) STORED,
    cri_score       NUMERIC(8,4)  GENERATED ALWAYS AS (((payload->'cri')->>'score')::numeric) STORED,
    cri_components  JSONB         GENERATED ALWAYS AS (payload->'cri'->'components') STORED,
    cta_exposure_pct NUMERIC(6,2) GENERATED ALWAYS AS (((payload->'cta')->>'exposure_pct')::numeric) STORED,
    cta_forced_reduction BOOLEAN  GENERATED ALWAYS AS (((payload->'cta')->>'forced_reduction')::boolean) STORED,
    cta_selling_usd_b NUMERIC(8,2) GENERATED ALWAYS AS (((payload->'cta')->>'selling_usd_b')::numeric) STORED,
    crash_trigger_fired BOOLEAN   GENERATED ALWAYS AS (((payload->'crash_trigger')->>'fired')::boolean) STORED
);

CREATE INDEX IF NOT EXISTS ix_cri_recorded_date ON uw_scan.cri_series (recorded_date);
CREATE INDEX IF NOT EXISTS ix_cri_recorded_at   ON uw_scan.cri_series (recorded_at DESC);

-- ── VCG series: vol-curve gauge snapshots (full column set from xenon db/schema.py:514-575) ──
CREATE TABLE IF NOT EXISTS uw_scan.vcg_series (
    id                   BIGSERIAL PRIMARY KEY,
    scanned_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    market_open          BOOLEAN,
    credit_proxy         TEXT,
    payload              JSONB NOT NULL,
    vcg                  NUMERIC(10,6) GENERATED ALWAYS AS (((payload->'signal')->>'vcg')::numeric) STORED,
    vcg_adj              NUMERIC(10,6) GENERATED ALWAYS AS (((payload->'signal')->>'vcg_adj')::numeric) STORED,
    residual             NUMERIC(12,8) GENERATED ALWAYS AS (((payload->'signal')->>'residual')::numeric) STORED,
    beta1_vvix           NUMERIC(12,8) GENERATED ALWAYS AS (((payload->'signal')->>'beta1_vvix')::numeric) STORED,
    beta2_vix            NUMERIC(12,8) GENERATED ALWAYS AS (((payload->'signal')->>'beta2_vix')::numeric) STORED,
    alpha                NUMERIC(12,8) GENERATED ALWAYS AS (((payload->'signal')->>'alpha')::numeric) STORED,
    vix                  NUMERIC(8,4)  GENERATED ALWAYS AS (((payload->'signal')->>'vix')::numeric) STORED,
    vvix                 NUMERIC(8,4)  GENERATED ALWAYS AS (((payload->'signal')->>'vvix')::numeric) STORED,
    credit_price         NUMERIC(10,4) GENERATED ALWAYS AS (((payload->'signal')->>'credit_price')::numeric) STORED,
    credit_5d_return_pct NUMERIC(8,4)  GENERATED ALWAYS AS (((payload->'signal')->>'credit_5d_return_pct')::numeric) STORED,
    ro                   SMALLINT      GENERATED ALWAYS AS (((payload->'signal')->>'ro')::int) STORED,
    edr                  SMALLINT      GENERATED ALWAYS AS (((payload->'signal')->>'edr')::int) STORED,
    tier                 SMALLINT      GENERATED ALWAYS AS (((payload->'signal')->>'tier')::int) STORED,
    bounce               SMALLINT      GENERATED ALWAYS AS (((payload->'signal')->>'bounce')::int) STORED,
    vvix_severity        TEXT          GENERATED ALWAYS AS ((payload->'signal')->>'vvix_severity') STORED,
    sign_ok              BOOLEAN       GENERATED ALWAYS AS (((payload->'signal')->>'sign_ok')::boolean) STORED,
    sign_suppressed      BOOLEAN       GENERATED ALWAYS AS (((payload->'signal')->>'sign_suppressed')::boolean) STORED,
    pi_panic             NUMERIC(8,4)  GENERATED ALWAYS AS (((payload->'signal')->>'pi_panic')::numeric) STORED,
    regime               TEXT          GENERATED ALWAYS AS ((payload->'signal')->>'regime') STORED,
    interpretation       TEXT          GENERATED ALWAYS AS ((payload->'signal')->>'interpretation') STORED,
    attr_vvix_pct        NUMERIC(6,2)  GENERATED ALWAYS AS (((payload->'signal'->'attribution')->>'vvix_pct')::numeric) STORED,
    attr_vix_pct         NUMERIC(6,2)  GENERATED ALWAYS AS (((payload->'signal'->'attribution')->>'vix_pct')::numeric) STORED,
    attr_vvix_component  NUMERIC(12,8) GENERATED ALWAYS AS (((payload->'signal'->'attribution')->>'vvix_component')::numeric) STORED,
    attr_vix_component   NUMERIC(12,8) GENERATED ALWAYS AS (((payload->'signal'->'attribution')->>'vix_component')::numeric) STORED,
    attr_model_implied   NUMERIC(12,8) GENERATED ALWAYS AS (((payload->'signal'->'attribution')->>'model_implied')::numeric) STORED,
    CONSTRAINT uq_vcg_series_scanned_at UNIQUE (scanned_at)
);

CREATE INDEX IF NOT EXISTS ix_vcg_scanned_at ON uw_scan.vcg_series (scanned_at DESC);
CREATE INDEX IF NOT EXISTS ix_vcg_regime     ON uw_scan.vcg_series (regime);
CREATE INDEX IF NOT EXISTS ix_vcg_tier       ON uw_scan.vcg_series (tier) WHERE tier IS NOT NULL;

-- ── GEX snapshots: gamma exposure per ticker per scan (full column set from xenon db/schema.py:577-641) ──
CREATE TABLE IF NOT EXISTS uw_scan.gex_snapshots (
    id              BIGSERIAL PRIMARY KEY,
    ticker          TEXT NOT NULL,
    data_date       DATE,
    scanned_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    payload         JSONB NOT NULL,
    spot            NUMERIC(12,4) GENERATED ALWAYS AS ((payload->>'spot')::numeric) STORED,
    net_gex         NUMERIC(14,2) GENERATED ALWAYS AS ((payload->>'net_gex')::numeric) STORED,
    net_dex         NUMERIC(14,2) GENERATED ALWAYS AS ((payload->>'net_dex')::numeric) STORED,
    vol_pc          NUMERIC(8,4)  GENERATED ALWAYS AS ((payload->>'vol_pc')::numeric) STORED,
    iv_30d          NUMERIC(6,4)  GENERATED ALWAYS AS (((payload->'iv')->>'iv30d')::numeric) STORED,
    iv_rank         NUMERIC(6,2)  GENERATED ALWAYS AS (((payload->'iv')->>'iv_rank')::numeric) STORED,
    hv_30d          NUMERIC(6,4)  GENERATED ALWAYS AS (((payload->'iv')->>'hv30')::numeric) STORED,
    mq_iv_30d       NUMERIC(6,4)  GENERATED ALWAYS AS (((payload->'iv')->>'mq_iv30d')::numeric) STORED,
    level_max_magnet_strike       NUMERIC(12,4) GENERATED ALWAYS AS (((payload->'levels'->'max_magnet')->>'strike')::numeric) STORED,
    level_max_magnet_gamma        NUMERIC(14,4) GENERATED ALWAYS AS (((payload->'levels'->'max_magnet')->>'gamma')::numeric) STORED,
    level_second_magnet_strike    NUMERIC(12,4) GENERATED ALWAYS AS (((payload->'levels'->'second_magnet')->>'strike')::numeric) STORED,
    level_second_magnet_gamma     NUMERIC(14,4) GENERATED ALWAYS AS (((payload->'levels'->'second_magnet')->>'gamma')::numeric) STORED,
    level_max_accelerator_strike  NUMERIC(12,4) GENERATED ALWAYS AS (((payload->'levels'->'max_accelerator')->>'strike')::numeric) STORED,
    level_max_accelerator_gamma   NUMERIC(14,4) GENERATED ALWAYS AS (((payload->'levels'->'max_accelerator')->>'gamma')::numeric) STORED,
    level_put_wall_strike         NUMERIC(12,4) GENERATED ALWAYS AS (((payload->'levels'->'put_wall')->>'strike')::numeric) STORED,
    level_call_wall_strike        NUMERIC(12,4) GENERATED ALWAYS AS (((payload->'levels'->'call_wall')->>'strike')::numeric) STORED,
    level_gex_flip_strike         NUMERIC(12,4) GENERATED ALWAYS AS (((payload->'levels'->'gex_flip')->>'strike')::numeric) STORED
);

CREATE INDEX IF NOT EXISTS ix_gex_ticker_time ON uw_scan.gex_snapshots (ticker, scanned_at DESC);
CREATE INDEX IF NOT EXISTS ix_gex_scanned_at  ON uw_scan.gex_snapshots (scanned_at DESC);
CREATE INDEX IF NOT EXISTS ix_gex_data_date   ON uw_scan.gex_snapshots (data_date);

COMMIT;
```

- [ ] **Step 2: Apply migration**

Run: `bash scripts/migrate.sh`
Expected: `Applying src/uw_scan/storage/migrations/037_regime_tables.sql...` followed by a `COMMIT` line, no errors. Re-running is a no-op.

- [ ] **Step 3: Verify tables**

Run:
```bash
psql "$(uv run python -c 'from uw_scan.config import Settings; print(Settings.from_env().db_dsn())')" -c "\d uw_scan.cri_series uw_scan.vcg_series uw_scan.gex_snapshots"
```
Expected: All three tables listed with `payload jsonb` column and generated columns visible.

- [ ] **Step 4: Commit**

```bash
git add src/uw_scan/storage/migrations/037_regime_tables.sql
git commit -m "feat(regime): add cri_series, vcg_series, gex_snapshots tables"
```

---

## Task 2: Pydantic response models — extend `src/uw_scan/api/schemas.py`

**Critical**: this repo's API-contract Pydantic models live in `src/uw_scan/api/schemas.py` (existing file; docstring: "Pydantic response models — over-the-wire contract for the watchlist API"). **Do NOT create `src/uw_scan/api/models/regime.py` — that directory does not exist and inventing it diverges from convention.**

**Files:**
- Modify (append to existing): `src/uw_scan/api/schemas.py`
- Create: `tests/unit/test_regime_schemas.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_regime_schemas.py`:

```python
from uw_scan.api.schemas import (
    CriResponse,
    EMPTY_CRI_RESPONSE,
    VcgResponse,
    EMPTY_VCG_RESPONSE,
    GexResponse,
    EMPTY_GEX_RESPONSE,
)


def test_empty_cri_response_serializes_with_nulls():
    payload = EMPTY_CRI_RESPONSE.model_dump()
    assert payload["vix"] is None
    assert payload["vvix"] is None
    assert payload["cri"]["score"] == 0
    assert payload["cri"]["level"] == "LOW"
    assert payload["history"] == []
    assert payload["spy_closes"] == []
    assert payload["crash_trigger"]["triggered"] is False


def test_cri_validator_coerces_string_numerics():
    """Replicates xenon normalizeCriPayload's asNumber behavior — strings cast to floats."""
    src = {"vix": "18.5", "vvix": "110.0", "spy": "580.2"}
    parsed = CriResponse.model_validate(src)
    assert parsed.vix == 18.5
    assert parsed.vvix == 110.0


def test_cri_validator_falls_back_invalid_level():
    """Bad CRI level strings should fall back to LOW per xenon route.ts:92-95."""
    src = {"cri": {"score": 50, "level": "WEIRD", "components": {"vix": 5, "vvix": 5, "correlation": 5, "momentum": 5}}}
    parsed = CriResponse.model_validate(src)
    assert parsed.cri.level == "LOW"


def test_cri_validator_filters_bad_spy_closes():
    """Non-numeric spy_closes entries dropped (xenon route.ts:77-81)."""
    src = {"spy_closes": [580.0, "not-a-number", 581.5, None, 582.0]}
    parsed = CriResponse.model_validate(src)
    assert parsed.spy_closes == [580.0, 581.5, 582.0]


def test_empty_vcg_response_includes_attribution_skeleton():
    payload = EMPTY_VCG_RESPONSE.model_dump()
    assert payload["signal"]["vcg"] is None
    assert payload["signal"]["attribution"]["vvix_pct"] is None
    assert payload["signal"]["credit_proxy"] is None or payload["credit_proxy"] is None


def test_empty_gex_response_uses_profile_not_buckets():
    """Frontend VcgPanel destructures data.profile, not data.buckets."""
    payload = EMPTY_GEX_RESPONSE.model_dump()
    assert "profile" in payload
    assert payload["profile"] == []
    assert payload["levels"]["max_magnet"] is None  # GexLevel is `... | null` in xenon
    assert "bias" in payload
    assert "iv" in payload
    assert "mq" in payload
    assert payload["mq"] is None  # MQ data optional
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_regime_schemas.py -v`
Expected: FAIL with `ImportError: cannot import name 'CriResponse' from 'uw_scan.api.schemas'`

- [ ] **Step 3: Implement models — append to `src/uw_scan/api/schemas.py`**

The model field set mirrors xenon's `CriData` (`web/lib/useRegime.ts`), `VcgData` (`web/lib/useVcg.ts:55-60`), `GexData` (`web/lib/useGex.ts:86-121`) **exactly**. Missing fields silently get filtered by FastAPI `response_model` and break the copied frontend panels.

Append at the end of `src/uw_scan/api/schemas.py`:

```python
# ─── Regime: CRI / VCG / GEX response shapes (ported from xenon 2026-05-16) ──
# Field sets mirror xenon/web/lib/useRegime.ts, useVcg.ts, useGex.ts. Adding/removing
# fields means rerunning `cd web && npm run gen:types` and updating the FE.

from typing import Literal
from pydantic import field_validator


CriLevel = Literal["LOW", "ELEVATED", "HIGH", "CRITICAL"]


class CriComponents(BaseModel):
    vix: float = 0
    vvix: float = 0
    correlation: float = 0
    momentum: float = 0


class Cri(BaseModel):
    score: float = 0
    level: CriLevel = "LOW"
    components: CriComponents = Field(default_factory=CriComponents)

    @field_validator("level", mode="before")
    @classmethod
    def _coerce_level(cls, v):
        """Mirror xenon route.ts:92-95 — unknown levels fall back to LOW."""
        return v if v in ("LOW", "ELEVATED", "HIGH", "CRITICAL") else "LOW"


class Cta(BaseModel):
    realized_vol: float = 0
    exposure_pct: float = 200
    forced_reduction_pct: float = 0
    est_selling_bn: float = 0


class CrashTriggerConditions(BaseModel):
    spx_below_100d_ma: bool = False
    realized_vol_gt_25: bool = False
    cor1m_gt_60: bool = False


class CrashTrigger(BaseModel):
    triggered: bool = False
    conditions: CrashTriggerConditions = Field(default_factory=CrashTriggerConditions)
    values: dict = Field(default_factory=dict)


class CriHistoryEntry(BaseModel):
    date: str
    vix: float | None = None
    vvix: float | None = None
    spy: float | None = None
    cor1m: float | None = None
    realized_vol: float | None = None
    spx_vs_ma_pct: float | None = None
    vix_5d_roc: float | None = None


class CriResponse(BaseModel):
    scan_time: str = ""
    date: str = ""
    market_open: bool | None = None
    vix: float | None = None
    vvix: float | None = None
    spy: float | None = None
    vix_5d_roc: float | None = None
    vvix_vix_ratio: float | None = None
    spx_100d_ma: float | None = None
    spx_distance_pct: float | None = None
    cor1m: float | None = None
    cor1m_previous_close: float | None = None
    cor1m_5d_change: float | None = None
    realized_vol: float | None = None
    cri: Cri = Field(default_factory=Cri)
    cta: Cta = Field(default_factory=Cta)
    menthorq_cta: dict | None = None
    crash_trigger: CrashTrigger = Field(default_factory=CrashTrigger)
    history: list[CriHistoryEntry] = Field(default_factory=list)
    spy_closes: list[float] = Field(default_factory=list)

    @field_validator(
        "vix", "vvix", "spy", "vix_5d_roc", "vvix_vix_ratio", "spx_100d_ma",
        "spx_distance_pct", "cor1m", "cor1m_previous_close", "cor1m_5d_change",
        "realized_vol",
        mode="before",
    )
    @classmethod
    def _coerce_number_or_none(cls, v):
        """Mirror xenon route.ts:55-61 — numeric strings cast to float; bad values → None."""
        if v is None:
            return None
        if isinstance(v, (int, float)):
            import math
            return v if math.isfinite(v) else None
        if isinstance(v, str):
            try:
                f = float(v)
                import math
                return f if math.isfinite(f) else None
            except ValueError:
                return None
        return None

    @field_validator("spy_closes", mode="before")
    @classmethod
    def _filter_bad_spy_closes(cls, v):
        """Mirror xenon route.ts:77-81 — drop non-numeric entries."""
        if not isinstance(v, list):
            return []
        out = []
        for entry in v:
            if isinstance(entry, (int, float)):
                import math
                if math.isfinite(entry):
                    out.append(float(entry))
            elif isinstance(entry, str):
                try:
                    f = float(entry)
                    import math
                    if math.isfinite(f):
                        out.append(f)
                except ValueError:
                    pass
        return out


EMPTY_CRI_RESPONSE = CriResponse()


# ── VCG ─────────────────────────────────────────────────────────────────

class VcgAttribution(BaseModel):
    vvix_pct: float | None = None
    vix_pct: float | None = None
    vvix_component: float | None = None
    vix_component: float | None = None
    model_implied: float | None = None


class VcgSignal(BaseModel):
    vcg: float | None = None
    vcg_adj: float | None = None
    residual: float | None = None
    beta1_vvix: float | None = None
    beta2_vix: float | None = None
    alpha: float | None = None
    vix: float | None = None
    vvix: float | None = None
    credit_price: float | None = None
    credit_5d_return_pct: float | None = None
    ro: int | None = None
    edr: int | None = None
    tier: int | None = None
    bounce: int | None = None
    vvix_severity: Literal["extreme", "elevated", "moderate"] | None = None
    sign_ok: bool | None = None
    sign_suppressed: bool | None = None
    pi_panic: float | None = None
    regime: Literal["PANIC", "TRANSITION", "DIVERGENCE"] | None = None
    interpretation: (
        Literal["RISK_OFF", "EDR", "WATCH", "BOUNCE", "NORMAL", "SUPPRESSED", "PANIC"]
        | None
    ) = None
    attribution: VcgAttribution = Field(default_factory=VcgAttribution)


class VcgHistoryEntry(BaseModel):
    date: str
    residual: float | None = None
    vcg: float | None = None
    vcg_adj: float | None = None
    beta1: float | None = None
    beta2: float | None = None
    vix: float | None = None
    vvix: float | None = None
    credit: float | None = None


class VcgResponse(BaseModel):
    scan_time: str = ""
    market_open: bool | None = None
    credit_proxy: str | None = None
    signal: VcgSignal = Field(default_factory=VcgSignal)
    history: list[VcgHistoryEntry] = Field(default_factory=list)


EMPTY_VCG_RESPONSE = VcgResponse()


# ── GEX ─────────────────────────────────────────────────────────────────

class GexLevel(BaseModel):
    strike: float
    gamma: float
    distance: float
    distance_pct: float


class GexLevels(BaseModel):
    # Each level is nullable (xenon: `GexLevel | null`)
    gex_flip: GexLevel | None = None
    max_magnet: GexLevel | None = None
    second_magnet: GexLevel | None = None
    max_accelerator: GexLevel | None = None
    put_wall: GexLevel | None = None
    call_wall: GexLevel | None = None


class GexBucket(BaseModel):
    strike: float
    call_gex: float
    put_gex: float
    net_gex: float
    pct_from_spot: float
    tag: str | None = None


class GexBiasFlipMigration(BaseModel):
    date: str
    flip: float


class GexBias(BaseModel):
    direction: Literal["BULL", "CAUTIOUS_BULL", "NEUTRAL", "CAUTIOUS_BEAR", "BEAR"] | None = None
    reasons: list[str] = Field(default_factory=list)
    days_above_flip: int | None = None
    flip_migration: list[GexBiasFlipMigration] = Field(default_factory=list)


class GexExpectedRange(BaseModel):
    low: float | None = None
    high: float | None = None
    iv_1d: float | None = None


class GexHistoryEntry(BaseModel):
    date: str
    net_gex: float | None = None
    net_dex: float | None = None
    gex_flip: float | None = None
    spot: float | None = None
    atm_iv: float | None = None
    vol_pc: float | None = None
    bias: str | None = None


class GexIvData(BaseModel):
    iv30d: float | None = None
    iv_rank: float | None = None
    hv30: float | None = None
    mq_iv30d: float | None = None
    mq_iv_rank: str | None = None
    source: Literal["uw", "mq", "both"] | None = None


class GexMqLevels(BaseModel):
    source_date: str | None = None
    spot: float | None = None
    hvl: float | None = None
    call_resistance_all: float | None = None
    call_resistance_0dte: float | None = None
    put_support_all: float | None = None
    put_support_0dte: float | None = None
    expected_high: float | None = None
    expected_low: float | None = None
    distance_to_hvl_pct: str | None = None
    iv30d: float | None = None
    hv30: float | None = None
    iv_rank: str | None = None
    top_gex_strikes: list[float] = Field(default_factory=list)


class GexSourceDeltaEntry(BaseModel):
    uw: float
    mq: float
    delta: float


class GexSourceDelta(BaseModel):
    flip_vs_hvl: GexSourceDeltaEntry | None = None
    put_wall_vs_support_all: GexSourceDeltaEntry | None = None
    put_wall_vs_support_0dte: GexSourceDeltaEntry | None = None
    call_wall_vs_resistance_all: GexSourceDeltaEntry | None = None
    call_wall_vs_resistance_0dte: GexSourceDeltaEntry | None = None


class GexResponse(BaseModel):
    scan_time: str = ""
    market_open: bool | None = None
    ticker: str = "SPX"
    spot: float | None = None
    close: float | None = None
    day_change: float | None = None
    day_change_pct: float | None = None
    data_date: str | None = None
    net_gex: float | None = None
    net_dex: float | None = None
    atm_iv: float | None = None
    vol_pc: float | None = None
    levels: GexLevels = Field(default_factory=GexLevels)
    profile: list[GexBucket] = Field(default_factory=list)
    expected_range: GexExpectedRange = Field(default_factory=GexExpectedRange)
    bias: GexBias = Field(default_factory=GexBias)
    history: list[GexHistoryEntry] = Field(default_factory=list)
    iv: GexIvData | None = None
    mq: GexMqLevels | None = None
    source_delta: GexSourceDelta | None = None


EMPTY_GEX_RESPONSE = GexResponse()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_regime_schemas.py -v`
Expected: 6 PASSED.

- [ ] **Step 5: Commit**

```bash
git add src/uw_scan/api/schemas.py tests/unit/test_regime_schemas.py
git commit -m "feat(regime): add CRI/VCG/GEX Pydantic schemas with normalize validators"
```

---

## Task 3: Repository methods on existing `Repository` class

**Critical**: per `CLAUDE.md` ("Repository pattern: src/uw_scan/storage/repository.py (one method per query)") and the existing 30+ methods on the class (see `repository.py:579` `class Repository`), regime queries are **methods on the existing class**, not a separate module. Test fixture is `seeded_db_empty_cards: Repository` from `tests/integration/conftest.py` — there is **no `pg_conn` fixture**.

**Files:**
- Modify (append methods to): `src/uw_scan/storage/repository.py`
- Create: `tests/integration/test_regime_repository.py`

- [ ] **Step 1: Write the failing test**

Create `tests/integration/test_regime_repository.py`:

```python
import json

from uw_scan.storage.repository import Repository


def test_fetch_latest_cri_returns_none_when_empty(seeded_db_empty_cards: Repository) -> None:
    assert seeded_db_empty_cards.fetch_latest_cri() is None


def test_fetch_latest_cri_returns_payload(seeded_db_empty_cards: Repository) -> None:
    repo = seeded_db_empty_cards
    payload = {"vix": 18.5, "vvix": 110.0, "cri": {"score": 42, "level": "ELEVATED"}}
    with repo.conn.cursor() as cur:
        cur.execute(
            "INSERT INTO uw_scan.cri_series (cri_level, payload) VALUES (%s, %s::jsonb)",
            (42, json.dumps(payload)),
        )
    repo.conn.commit()
    result = repo.fetch_latest_cri()
    assert result is not None
    assert result["vix"] == 18.5
    assert result["cri"]["score"] == 42


def test_fetch_cri_history_orders_by_date(seeded_db_empty_cards: Repository) -> None:
    repo = seeded_db_empty_cards
    with repo.conn.cursor() as cur:
        for day, score in [("2026-05-14", 30), ("2026-05-15", 40), ("2026-05-16", 50)]:
            cur.execute(
                "INSERT INTO uw_scan.cri_series (cri_level, payload) VALUES (%s, %s::jsonb)",
                (score, json.dumps({"date": day, "cri": {"score": score}})),
            )
    repo.conn.commit()
    history = repo.fetch_cri_history(limit=10)
    assert len(history) == 3
    assert [h["cri_score"] for h in history] == [30, 40, 50]


def test_fetch_latest_gex_filters_by_ticker(seeded_db_empty_cards: Repository) -> None:
    repo = seeded_db_empty_cards
    with repo.conn.cursor() as cur:
        cur.execute(
            "INSERT INTO uw_scan.gex_snapshots (ticker, payload) VALUES (%s, %s::jsonb)",
            ("SPX", json.dumps({"spot": 5800.0})),
        )
        cur.execute(
            "INSERT INTO uw_scan.gex_snapshots (ticker, payload) VALUES (%s, %s::jsonb)",
            ("SPY", json.dumps({"spot": 580.0})),
        )
    repo.conn.commit()
    spx = repo.fetch_latest_gex(ticker="SPX")
    spy = repo.fetch_latest_gex(ticker="SPY")
    assert spx["spot"] == 5800.0
    assert spy["spot"] == 580.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/integration/test_regime_repository.py -v`
Expected: FAIL with `AttributeError: 'Repository' object has no attribute 'fetch_latest_cri'`.

- [ ] **Step 3: Add methods to the `Repository` class**

Open `src/uw_scan/storage/repository.py`. Find the `class Repository:` line (around line 579). Append these methods inside the class body (anywhere after the existing methods is fine — match the existing indentation):

```python
    # ─── Regime (CRI / VCG / GEX) — ported from xenon 2026-05-16 ──────────

    def fetch_latest_cri(self) -> dict | None:
        """Return the most-recent cri_series payload, or None when empty."""
        with self.conn.cursor() as cur:
            cur.execute(
                f"SELECT payload, recorded_at FROM {self._schema}.cri_series "
                f"ORDER BY recorded_at DESC LIMIT 1"
            )
            row = cur.fetchone()
        if row is None:
            return None
        payload, recorded_at = row[0] or {}, row[1]
        out = dict(payload)
        out.setdefault("scan_time", recorded_at.isoformat() if recorded_at else "")
        return out

    def fetch_cri_history(self, *, limit: int = 90) -> list[dict]:
        """Return CRI history ascending (oldest first), for line-chart rendering."""
        with self.conn.cursor() as cur:
            cur.execute(
                f"SELECT payload, recorded_date, recorded_at, vix, vvix, spy, cor1m, "
                f"cri_score, realized_vol "
                f"FROM {self._schema}.cri_series "
                f"ORDER BY recorded_at DESC LIMIT %s",
                (limit,),
            )
            rows = cur.fetchall()
        rows.reverse()
        out: list[dict] = []
        for payload, recorded_date, recorded_at, vix, vvix, spy, cor1m, cri_score, rvol in rows:
            data = dict(payload or {})
            out.append({
                "date": data.get("date") or (recorded_date.isoformat() if recorded_date else (recorded_at.isoformat() if recorded_at else "")),
                "cri_score": float(cri_score) if cri_score is not None else None,
                "vix": float(vix) if vix is not None else None,
                "vvix": float(vvix) if vvix is not None else None,
                "spy": float(spy) if spy is not None else None,
                "cor1m": float(cor1m) if cor1m is not None else None,
                "realized_vol": float(rvol) if rvol is not None else None,
            })
        return out

    def fetch_latest_vcg(self) -> dict | None:
        with self.conn.cursor() as cur:
            cur.execute(
                f"SELECT payload, scanned_at, market_open FROM {self._schema}.vcg_series "
                f"ORDER BY scanned_at DESC LIMIT 1"
            )
            row = cur.fetchone()
        if row is None:
            return None
        payload, scanned_at, market_open = row[0] or {}, row[1], row[2]
        out = dict(payload)
        out.setdefault("scan_time", scanned_at.isoformat() if scanned_at else "")
        if "market_open" not in out:
            out["market_open"] = market_open
        return out

    def fetch_latest_gex(self, *, ticker: str = "SPX") -> dict | None:
        with self.conn.cursor() as cur:
            cur.execute(
                f"SELECT payload, scanned_at, ticker FROM {self._schema}.gex_snapshots "
                f"WHERE ticker = %s ORDER BY scanned_at DESC LIMIT 1",
                (ticker,),
            )
            row = cur.fetchone()
        if row is None:
            return None
        payload, scanned_at, t = row[0] or {}, row[1], row[2]
        out = dict(payload)
        out.setdefault("scan_time", scanned_at.isoformat() if scanned_at else "")
        out.setdefault("ticker", t)
        return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `UW_SCAN_TEST_DB_NAME=option_wizard_test uv run pytest tests/integration/test_regime_repository.py -v`
Expected: 4 PASSED. (The `UW_SCAN_TEST_DB_NAME` is set in `tests/conftest.py` to default `option_wizard_test`; exporting explicitly is just defensive.)

- [ ] **Step 5: Commit**

```bash
git add src/uw_scan/storage/repository.py tests/integration/test_regime_repository.py
git commit -m "feat(regime): add fetch_latest_cri / fetch_cri_history / fetch_latest_vcg / fetch_latest_gex"
```

---

## Task 4: FastAPI regime router

**Critical conventions** (verified against `src/uw_scan/api/routers/cockpit.py` and `tests/integration/api/conftest.py`):
- DI is `Annotated[Repository, Depends(get_repo)]` from `uw_scan.api.deps`. **`get_db_connection` does NOT exist — never reference it.**
- Tests use the `client: TestClient` fixture from `tests/integration/api/conftest.py:30` which already wires `app.dependency_overrides[get_repo]` to the test DB. **Do NOT instantiate `TestClient(app)` directly** — that bypasses overrides.
- For monkeypatching repo methods on the `Repository` class, use `monkeypatch.setattr(Repository, "fetch_latest_cri", ...)` style.

**Files:**
- Create: `src/uw_scan/api/routers/regime.py`
- Modify: `src/uw_scan/api/server.py` (imports + `include_router` line after `trade_insights.router`)
- Create: `tests/integration/api/test_regime_router.py`

- [ ] **Step 1: Write the failing test**

Create `tests/integration/api/test_regime_router.py`:

```python
from fastapi.testclient import TestClient

from uw_scan.storage.repository import Repository


def test_get_regime_returns_empty_shape_when_no_data(client: TestClient, monkeypatch) -> None:
    monkeypatch.setattr(Repository, "fetch_latest_cri", lambda self: None)
    monkeypatch.setattr(Repository, "fetch_cri_history", lambda self, *, limit=90: [])
    response = client.get("/api/regime")
    assert response.status_code == 200
    data = response.json()
    assert data["vix"] is None
    assert data["cri"]["score"] == 0
    assert data["cri"]["level"] == "LOW"
    assert data["history"] == []
    assert data["crash_trigger"]["triggered"] is False


def test_post_cri_scan_returns_202_with_stub_body(client: TestClient) -> None:
    response = client.post("/api/regime/scan")
    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "queued"
    assert body["scanner"] == "cri"
    assert "scanner_pending" in body["message"].lower()


def test_post_vcg_scan_returns_202(client: TestClient) -> None:
    response = client.post("/api/regime/vcg/scan")
    assert response.status_code == 202
    assert response.json()["scanner"] == "vcg"


def test_post_gex_scan_returns_202_with_ticker_echo(client: TestClient) -> None:
    response = client.post("/api/regime/gex/scan?ticker=spy")
    assert response.status_code == 202
    body = response.json()
    assert body["scanner"] == "gex"
    assert body["ticker"] == "SPY"


def test_get_vcg_returns_empty_shape_when_no_data(client: TestClient, monkeypatch) -> None:
    monkeypatch.setattr(Repository, "fetch_latest_vcg", lambda self: None)
    response = client.get("/api/regime/vcg")
    assert response.status_code == 200
    data = response.json()
    assert data["signal"]["vcg"] is None
    assert data["history"] == []
    assert data["signal"]["attribution"]["vvix_pct"] is None  # full xenon shape


def test_get_gex_defaults_to_spx_and_uppercases_ticker(client: TestClient, monkeypatch) -> None:
    seen: dict[str, str] = {}

    def _stub_fetch(self, *, ticker="SPX"):
        seen["ticker"] = ticker
        return None

    monkeypatch.setattr(Repository, "fetch_latest_gex", _stub_fetch)

    response = client.get("/api/regime/gex")
    assert response.status_code == 200
    assert seen["ticker"] == "SPX"  # default

    response = client.get("/api/regime/gex?ticker=spy")
    assert seen["ticker"] == "SPY"  # uppercased

    data = response.json()
    assert data["spot"] is None
    assert data["levels"]["max_magnet"] is None  # GexLevel | None
    assert data["profile"] == []  # NOT "buckets" — xenon uses `profile`
    assert data["bias"]["direction"] is None
    assert data["mq"] is None


def test_get_regime_market_open_overrides_stored_value(client: TestClient, monkeypatch) -> None:
    monkeypatch.setattr(Repository, "fetch_latest_cri", lambda self: {"market_open": False, "vix": 18.5})
    monkeypatch.setattr(Repository, "fetch_cri_history", lambda self, *, limit=90: [])
    monkeypatch.setattr("uw_scan.api.routers.regime._is_market_open_now", lambda: True)
    response = client.get("/api/regime")
    assert response.json()["market_open"] is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/integration/api/test_regime_router.py -v`
Expected: FAIL — `/api/regime` returns 404 (router not registered).

- [ ] **Step 3: Implement router**

Create `src/uw_scan/api/routers/regime.py`:

```python
"""Read-only /regime surface — CRI, VCG, GEX summaries.

Mirrors the payload shape that xenon's Next.js /api/regime expects after
``normalizeCriPayload``. Scanner internals are out of scope here; this router
hands back the latest persisted row (or the EMPTY_* default when tables are
empty) and a 202 stub for /scan until the backfill phase wires data sources.
"""
from __future__ import annotations

from datetime import datetime
from typing import Annotated
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Query

from uw_scan.api.deps import get_repo
from uw_scan.api.schemas import (
    EMPTY_CRI_RESPONSE,
    EMPTY_GEX_RESPONSE,
    EMPTY_VCG_RESPONSE,
    CriResponse,
    GexResponse,
    VcgResponse,
)
from uw_scan.storage.repository import Repository

router = APIRouter(prefix="/regime")


def _is_market_open_now() -> bool:
    """Mirror xenon's isMarketOpenNow() — current ET clock, Mon-Fri 09:30-16:00."""
    now = datetime.now(ZoneInfo("America/New_York"))
    if now.weekday() >= 5:
        return False
    minutes = now.hour * 60 + now.minute
    return 9 * 60 + 30 <= minutes <= 16 * 60


@router.get("", response_model=CriResponse)
def get_regime(
    repo: Annotated[Repository, Depends(get_repo)],
) -> CriResponse:
    raw = repo.fetch_latest_cri()
    if raw is None:
        empty = EMPTY_CRI_RESPONSE.model_copy(deep=True)
        empty.market_open = _is_market_open_now()
        return empty
    raw.setdefault("history", repo.fetch_cri_history(limit=90))
    raw["market_open"] = _is_market_open_now()
    return CriResponse.model_validate(raw)


@router.post("/scan", status_code=202)
def trigger_cri_scan() -> dict[str, str]:
    """Stub: CRI scanner port happens in a follow-up backfill plan."""
    return {
        "status": "queued",
        "scanner": "cri",
        "message": "scanner_pending: data sources not yet wired (VIX/VVIX/COR1M)",
    }


@router.get("/vcg", response_model=VcgResponse)
def get_vcg(
    repo: Annotated[Repository, Depends(get_repo)],
) -> VcgResponse:
    raw = repo.fetch_latest_vcg()
    if raw is None:
        empty = EMPTY_VCG_RESPONSE.model_copy(deep=True)
        empty.market_open = _is_market_open_now()
        return empty
    raw["market_open"] = _is_market_open_now()
    return VcgResponse.model_validate(raw)


@router.post("/vcg/scan", status_code=202)
def trigger_vcg_scan() -> dict[str, str]:
    """Stub: VCG scanner port happens in a follow-up backfill plan."""
    return {
        "status": "queued",
        "scanner": "vcg",
        "message": "scanner_pending: vcg.py port not yet wired",
    }


@router.get("/gex", response_model=GexResponse)
def get_gex(
    repo: Annotated[Repository, Depends(get_repo)],
    ticker: str = Query("SPX"),
) -> GexResponse:
    raw = repo.fetch_latest_gex(ticker=ticker.upper())
    if raw is None:
        empty = EMPTY_GEX_RESPONSE.model_copy(deep=True)
        empty.market_open = _is_market_open_now()
        empty.ticker = ticker.upper()
        return empty
    raw["market_open"] = _is_market_open_now()
    return GexResponse.model_validate(raw)


@router.post("/gex/scan", status_code=202)
def trigger_gex_scan(ticker: str = Query("SPX")) -> dict[str, str]:
    """Stub: GEX scanner port happens in a follow-up backfill plan."""
    return {
        "status": "queued",
        "scanner": "gex",
        "ticker": ticker.upper(),
        "message": "scanner_pending: gex.py port not yet wired",
    }
```

- [ ] **Step 4: Register router in server.py**

In `src/uw_scan/api/server.py`, find the block of `app.include_router(...)` calls. After the last existing line in that block (currently `trade_insights.router`), add:

```python
from uw_scan.api.routers import regime  # add to imports near the other router imports

app.include_router(regime.router, prefix="/api", tags=["regime"])
```

(Place the import next to the other router imports near the top of `server.py`. Place the `include_router` call after the last existing one in the sequential block around `server.py:42`.)

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/integration/api/test_regime_router.py -v`
Expected: 7 PASSED.

- [ ] **Step 6: Smoke test the route locally — KEEP THE API RUNNING FOR TASK 5**

Start API: `uv run uvicorn uw_scan.api.server:app --port 8400 &` (or `bash scripts/dev.sh` in a separate terminal — `dev.sh` also starts the web app + workers, which is fine)
Run: `curl -s http://localhost:8400/api/regime | python -m json.tool | head -30`
Expected: JSON with `"vix": null`, `"cri": {"score": 0, "level": "LOW", ...}`, `"history": []`.

**Do NOT stop the API yet** — Task 5 (`gen:types`) needs it running on port 8400.

- [ ] **Step 7: Commit**

```bash
git add src/uw_scan/api/routers/regime.py src/uw_scan/api/server.py tests/integration/api/test_regime_router.py
git commit -m "feat(regime): expose GET /api/regime, POST /scan, GET /vcg, GET /gex"
```

---

## Task 5: Regenerate openapi types for frontend

**Prerequisite**: API server must be running on port 8400 (continued from Task 4 Step 6). `web/package.json`:`gen:types` fetches `http://127.0.0.1:8400/openapi.json`. If the API isn't running, this task fails immediately.

- [ ] **Step 1: Confirm API is reachable**

Run: `curl -sI http://localhost:8400/openapi.json | head -1`
Expected: `HTTP/1.1 200 OK`. If 404 or connection refused, restart the API: `uv run uvicorn uw_scan.api.server:app --port 8400 &`.

- [ ] **Step 2: Run codegen**

Run: `cd web && npm run gen:types`
Expected: `web/lib/types.ts` updated; diff shows new `CriResponse`/`VcgResponse`/`GexResponse`/`VcgSignal`/`VcgAttribution`/`GexLevel`/`GexBucket`/`GexBias`/`GexIvData`/`GexMqLevels`/`GexSourceDelta` schemas in `components.schemas`.

- [ ] **Step 3: Verify types compile**

Run: `cd web && npx tsc --noEmit`
Expected: No type errors.

- [ ] **Step 4: Stop the API server**

Run: `kill %1` (if you backgrounded uvicorn earlier) or Ctrl+C in the terminal running it.

- [ ] **Step 5: Commit**

```bash
git add web/lib/types.ts
git commit -m "chore(regime): regenerate openapi types for regime endpoints"
```

---

## Task 6: Frontend lib — fetch hooks + helpers

Before this task, inspect this repo's existing fetch pattern: `grep -rn "fetch(" web/lib/ web/components/ | head -10`. Hooks must use the same pattern (likely a typed `apiFetch` wrapper or direct `fetch`). The xenon `xenonFetch` is xenon-specific — DO NOT copy.

**Files:**
- Create: `web/lib/regime/types.ts` (re-exports of generated types under stable names)
- Create: `web/lib/regime/useRegime.ts`
- Create: `web/lib/regime/useVcg.ts`
- Create: `web/lib/regime/useGex.ts`
- Create: `web/lib/regime/useMarketHours.ts` (ports xenon's 81-LOC `MarketState` enum + ET clock hook)
- Create: `web/lib/regime/pricesProtocol.ts` (`PriceData` type only — kept for prop signatures even with empty prices)
- Create: `web/lib/regime/criCalc.ts`
- Create: `web/lib/regime/criStaleness.ts`
- Create: `web/lib/regime/regimeHistory.ts`
- Create: `web/lib/regime/regimeLiveStrip.ts`
- Create: `web/lib/regime/regimeRelationships.ts`
- Create: `web/lib/regime/sectionTooltips.ts` (verbatim port of CRI/VCG/GEX tooltip text constants)
- Create: `web/lib/regime/chartSystem.ts` (only `chartSeriesColor`'s string-keyed lookup map)

**Critical**: hooks must use the existing `API` constant from `web/lib/api.ts:3` (`process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8400"`). Bare `fetch("/api/regime")` in dev hits Next.js port 3001, not the FastAPI server.

Hook signatures must mirror xenon: each returns `UseSyncReturn<T>` and accepts `marketState` (and `useGex` also accepts `ticker`). The copied VcgPanel/GexPanel files destructure `loading` / `syncNow` from these returns — changing the shape forces rewriting both 400+ LOC components.

- [ ] **Step 1: Verify generated type names**

Run: `grep -nE 'CriResponse|VcgResponse|GexResponse' web/lib/types.ts | head -10`
Expected: At least one match per response type (under `components.schemas`).

- [ ] **Step 2: Create stable type re-exports**

Write `web/lib/regime/types.ts`:

```typescript
import type { components } from "@/lib/types";

// CRI — xenon: CriData
export type CriData = components["schemas"]["CriResponse"];
export type CriHistoryEntry = components["schemas"]["CriHistoryEntry"];
export type Cri = components["schemas"]["Cri"];
export type CriLevel = Cri["level"];
export type Cta = components["schemas"]["Cta"];
export type CrashTrigger = components["schemas"]["CrashTrigger"];

// VCG — xenon: VcgData, VcgSignal, VcgHistoryEntry
export type VcgData = components["schemas"]["VcgResponse"];
export type VcgSignal = components["schemas"]["VcgSignal"];
export type VcgAttribution = components["schemas"]["VcgAttribution"];
export type VcgHistoryEntry = components["schemas"]["VcgHistoryEntry"];

// GEX — xenon: GexData, GexLevel, GexBucket, GexBias, GexHistoryEntry, MqLevels, SourceDelta, IvData
export type GexData = components["schemas"]["GexResponse"];
export type GexLevel = components["schemas"]["GexLevel"] | null;
export type GexLevels = components["schemas"]["GexLevels"];
export type GexBucket = components["schemas"]["GexBucket"];
export type GexBias = components["schemas"]["GexBias"];
export type GexHistoryEntry = components["schemas"]["GexHistoryEntry"];
export type GexExpectedRange = components["schemas"]["GexExpectedRange"];
export type MqLevels = components["schemas"]["GexMqLevels"];
export type SourceDelta = components["schemas"]["GexSourceDelta"];
export type SourceDeltaEntry = components["schemas"]["GexSourceDeltaEntry"];
export type IvData = components["schemas"]["GexIvData"];
```

- [ ] **Step 3: Port `useSyncHook` (REQUIRED — all 3 hooks depend on it)**

Copy `/Users/chenxi/projects/xenon/web/lib/useSyncHook.ts` (236 LOC) → `web/lib/regime/useSyncHook.ts`. No external imports beyond React — should compile as-is. Exports: `useSyncHook<T>(config)`, type `UseSyncReturn<T>` (`{data, loading, syncing, error, lastSync, syncNow}`).

- [ ] **Step 4: Create `web/lib/regime/api.ts` — typed wrapper using the shared API base URL**

Write `web/lib/regime/api.ts`:

```typescript
const API = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8400";

export const regimeApi = {
  cri: () => `${API}/api/regime`,
  cri_scan: () => `${API}/api/regime/scan`,
  vcg: () => `${API}/api/regime/vcg`,
  vcg_scan: () => `${API}/api/regime/vcg/scan`,
  gex: (ticker: string) => `${API}/api/regime/gex?ticker=${encodeURIComponent(ticker)}`,
  gex_scan: (ticker: string) => `${API}/api/regime/gex/scan?ticker=${encodeURIComponent(ticker)}`,
} as const;
```

- [ ] **Step 5: Port useRegime / useVcg / useGex (mirror xenon signatures via `useSyncHook`)**

Open `/Users/chenxi/projects/xenon/web/lib/useRegime.ts`. Copy → `web/lib/regime/useRegime.ts`. Adjust:
- `import { useSyncHook, type UseSyncReturn } from "./useSyncHook"` stays (sibling, ported in Step 3)
- `import { MarketState } from "./useMarketHours"` stays (ported in Step 7 below)
- Replace any hardcoded endpoint string with `regimeApi.cri()` from `./api`

Open `/Users/chenxi/projects/xenon/web/lib/useVcg.ts`. Copy → `web/lib/regime/useVcg.ts`. Same adjustments; endpoint `regimeApi.vcg()`.

Open `/Users/chenxi/projects/xenon/web/lib/useGex.ts`. Copy → `web/lib/regime/useGex.ts`. Same adjustments; endpoint `regimeApi.gex(ticker)`. **Change the default `ticker` parameter from `"SPY"` (xenon Next.js wrapper) to `"SPX"`** — matches the FastAPI default and the GEX panel's primary use case.

The hook signatures, return shapes, retry/poll logic, and module-level cache all come from xenon unchanged. Do NOT rewrite the bodies inline.

- [ ] **Step 6: Port criCalc helper**

Copy `/Users/chenxi/projects/xenon/web/lib/criCalc.ts` (103 LOC) → `web/lib/regime/criCalc.ts`. No external `@/lib/...` imports — copies as-is.

- [ ] **Step 7: Port useMarketHours**

Copy `/Users/chenxi/projects/xenon/web/lib/useMarketHours.ts` (81 LOC, no external deps) → `web/lib/regime/useMarketHours.ts`. Exports: `MarketState` enum + `useMarketHours()` hook.

- [ ] **Step 8: Port pricesProtocol type**

Copy `/Users/chenxi/projects/xenon/web/lib/pricesProtocol.ts` (207 LOC) → `web/lib/regime/pricesProtocol.ts`. Exports `PriceData` type used in component signatures.

- [ ] **Step 9: Port regimeHistory**

Copy `/Users/chenxi/projects/xenon/web/lib/regimeHistory.ts` (66 LOC) → `web/lib/regime/regimeHistory.ts`. Exports `backfillRealizedVolHistory`.

- [ ] **Step 10: Port criStaleness**

Copy `/Users/chenxi/projects/xenon/web/lib/criStaleness.ts` (57 LOC) → `web/lib/regime/criStaleness.ts`. Exports `isCriDataStale`.

- [ ] **Step 11: Port regimeLiveStrip**

Copy `/Users/chenxi/projects/xenon/web/lib/regimeLiveStrip.ts` (97 LOC) → `web/lib/regime/regimeLiveStrip.ts`. Adjust any `@/lib/criStaleness` → `@/lib/regime/criStaleness` etc.

- [ ] **Step 12: Port regimeRelationships**

Copy `/Users/chenxi/projects/xenon/web/lib/regimeRelationships.ts` (174 LOC) → `web/lib/regime/regimeRelationships.ts`. Adjust imports to point at `@/lib/regime/*`.

- [ ] **Step 13: Port sectionTooltips (subset — regime keys only)**

Open `/Users/chenxi/projects/xenon/web/lib/sectionTooltips.ts`. Identify which keys regime files reference:

```bash
grep -RhE 'SECTION_TOOLTIPS\["[^"]+"\]' \
  /Users/chenxi/projects/xenon/web/components/RegimePanel.tsx \
  /Users/chenxi/projects/xenon/web/components/VcgPanel.tsx \
  /Users/chenxi/projects/xenon/web/components/GexPanel.tsx \
  /Users/chenxi/projects/xenon/web/components/RegimeRelationshipView.tsx \
  | sort -u
```

Create `web/lib/regime/sectionTooltips.ts` exporting **only those keys** as a `SECTION_TOOLTIPS` const. Do NOT pull xenon-only keys (positions/orders/wizards).

- [ ] **Step 14: Port chartSystem (named-color helper only, STRING-keyed)**

Open `/Users/chenxi/projects/xenon/web/lib/chartSystem.ts` (48 LOC). Port `chartSeriesColor(name: string): string` + its name→CSS-var lookup map. **The function signature takes a string token (e.g. `"caution"`, `"dislocation"`), NOT a numeric index** — see `RegimePanel.tsx:460-461`. A numeric-index fallback would break call sites. Skip any unused exports.

- [ ] **Step 15: Verify the lib bundle type-checks**

Run: `cd web && npx tsc --noEmit`
Expected: No errors. If any helper still references a missing `@/lib/...` path, adjust by either:
  - Pointing at the ported sibling under `@/lib/regime/*`, OR
  - Inlining the missing constant/type if it's tiny (1-5 lines).

- [ ] **Step 16: Commit**

```bash
git add web/lib/regime/
git commit -m "feat(regime): port frontend regime libs (useSyncHook + hooks + market hours + relationships)"
```

---

## Task 7: Frontend components — RegimePanel shell with 3 sub-tabs

**Files:**
- Create: `web/components/regime/RegimePanel.tsx`
- Create: `web/components/regime/InfoTooltip.tsx` (skip if already present anywhere — check first)

- [ ] **Step 1: Check for existing InfoTooltip**

Run: `find web/components -name "InfoTooltip.tsx" -not -path "*/regime/*"`
Expected: Empty result OR one path.

If found: reuse it; skip Step 2. If not: continue to Step 2.

- [ ] **Step 2: Port InfoTooltip from xenon**

Copy `/Users/chenxi/projects/xenon/web/components/InfoTooltip.tsx` → `web/components/regime/InfoTooltip.tsx`. Adjust imports if needed.

- [ ] **Step 3: Write RegimePanel shell**

The shell owns `marketState` (from `useMarketHours`) and the `prices` map (empty `{}` for now — see `MetricCard.tsx` prop drilling), then forwards both to each sub-tab. This mirrors xenon's RegimePanel signature so the eventual live-price wiring is a one-line change.

Write `web/components/regime/RegimePanel.tsx`:

```typescript
"use client";

import { useState } from "react";
import CriSubTab from "./CriSubTab";
import VcgSubTab from "./VcgSubTab";
import GexSubTab from "./GexSubTab";
import { useMarketHours } from "@/lib/regime/useMarketHours";
import type { PriceData } from "@/lib/regime/pricesProtocol";

type RegimeTab = "cri" | "vcg" | "gex";

const EMPTY_PRICES: Record<string, PriceData> = {};

export default function RegimePanel() {
  const [activeTab, setActiveTab] = useState<RegimeTab>("cri");
  const marketState = useMarketHours();

  const tabBar = (
    <div className="ticker-tabs" style={{ marginBottom: "16px" }} data-testid="regime-tabs">
      <button
        className={`ticker-tab ${activeTab === "cri" ? "active" : ""}`}
        onClick={() => setActiveTab("cri")}
        data-testid="regime-tab-cri"
      >
        CRI
      </button>
      <button
        className={`ticker-tab ${activeTab === "vcg" ? "active" : ""}`}
        onClick={() => setActiveTab("vcg")}
        data-testid="regime-tab-vcg"
      >
        VCG
      </button>
      <button
        className={`ticker-tab ${activeTab === "gex" ? "active" : ""}`}
        onClick={() => setActiveTab("gex")}
        data-testid="regime-tab-gex"
      >
        GEX
      </button>
    </div>
  );

  return (
    <div className="regime-panel" data-testid="regime-panel">
      {tabBar}
      {activeTab === "cri" && <CriSubTab prices={EMPTY_PRICES} marketState={marketState} />}
      {activeTab === "vcg" && <VcgSubTab prices={EMPTY_PRICES} marketState={marketState} />}
      {activeTab === "gex" && <GexSubTab marketState={marketState} />}
    </div>
  );
}
```

- [ ] **Step 4: Commit**

```bash
git add web/components/regime/RegimePanel.tsx web/components/regime/InfoTooltip.tsx
git commit -m "feat(regime): RegimePanel shell with CRI/VCG/GEX tab nav"
```

---

## Task 8: CRI sub-tab (visual port — incl. d3 install + chart wrappers + Sync Now)

**d3 dependency** (deviation from CLAUDE.md "no chart library", user-approved 2026-05-16 for 1:1 visual mirror): both `CriHistoryChart.tsx:4` and `RegimeRelationshipView.tsx:4` import `* as d3 from "d3"`. The plan installs `d3` + `@types/d3` and ports xenon's `charts/ChartPanel.tsx` (69 LOC) + `charts/ChartLegend.tsx` (27 LOC) so the copied components compile.

**Files:**
- Modify: `web/package.json` (add `d3` + `@types/d3`)
- Create: `web/components/regime/CriSubTab.tsx`
- Create: `web/components/regime/CriHistoryChart.tsx`
- Create: `web/components/regime/RegimeStrip.tsx`
- Create: `web/components/regime/RegimeRelationshipView.tsx`
- Create: `web/components/regime/charts/ChartPanel.tsx`
- Create: `web/components/regime/charts/ChartLegend.tsx`

- [ ] **Step 1: Install d3**

```bash
cd web && npm install d3 @types/d3 --save
```
Expected: `package.json` gains `"d3"` under `dependencies` and `"@types/d3"` under `devDependencies`. No errors.

Document the deviation: append a comment near the new entries in `package.json`:

```jsonc
// d3 + @types/d3 added 2026-05-16 for regime/* CriHistoryChart + RegimeRelationshipView
// (1:1 port from xenon). Scoped use only — other charts in this repo remain hand-rolled SVG
// per CLAUDE.md.
```

(JSON doesn't support comments — put this note in the PR description and any new top-level README/docs reference instead. The package.json itself stays as standard JSON.)

- [ ] **Step 2: Port ChartPanel + ChartLegend wrappers**

Copy `/Users/chenxi/projects/xenon/web/components/charts/ChartPanel.tsx` → `web/components/regime/charts/ChartPanel.tsx`.
Copy `/Users/chenxi/projects/xenon/web/components/charts/ChartLegend.tsx` → `web/components/regime/charts/ChartLegend.tsx`.

Both are small (~95 LOC combined) and have no further `@/lib/...` dependencies. Adjust imports only if they reference `@/lib/chartSystem` — point at `@/lib/regime/chartSystem`.

- [ ] **Step 3: Port CriHistoryChart**

Copy `/Users/chenxi/projects/xenon/web/components/CriHistoryChart.tsx` (346 LOC) → `web/components/regime/CriHistoryChart.tsx`. Adjust:
- `import * as d3 from "d3"` stays (now installed in Step 1)
- `import ChartPanel from "./charts/ChartPanel"` stays (now sibling under regime/charts/)
- Any `@/lib/chartSystem` → `@/lib/regime/chartSystem`

- [ ] **Step 4: Port RegimeStrip**

Copy `/Users/chenxi/projects/xenon/web/components/RegimeStrip.tsx` (79 LOC) → `web/components/regime/RegimeStrip.tsx`. Exports: `LiveBadge`, `DayChange`, `PointChange`, `RegimeStripCell`, default `RegimeStrip`. No external deps beyond `lucide-react`.

- [ ] **Step 5: Port RegimeRelationshipView**

Copy `/Users/chenxi/projects/xenon/web/components/RegimeRelationshipView.tsx` (693 LOC) → `web/components/regime/RegimeRelationshipView.tsx`. Adjust imports:
- `import * as d3 from "d3"` stays (installed in Step 1)
- `@/lib/regimeRelationships` → `@/lib/regime/regimeRelationships`
- `@/lib/chartSystem` → `@/lib/regime/chartSystem`
- `@/lib/sectionTooltips` → `@/lib/regime/sectionTooltips`
- `./charts/ChartLegend` → `./charts/ChartLegend` (sibling stays, file is at `web/components/regime/charts/ChartLegend.tsx`)
- `./charts/ChartPanel` → `./charts/ChartPanel` (sibling stays)
- `./InfoTooltip` stays (sibling in regime/)

With empty history (`data.history === []`), it renders the empty-state skeleton.

- [ ] **Step 6: Port CriSubTab from RegimePanel.tsx**

Open `/Users/chenxi/projects/xenon/web/components/RegimePanel.tsx`. The CRI rendering spans:
- Lines 105–270: hook calls, state, derived values (`computeCri`, `levelColor`, helpers)
- Lines 300–407: `RegimeStrip` with 6 `RegimeStripCell`s (VIX/VVIX/SPY/COR1M/RVOL/CRI)
- Lines 408–474: hero (score + level badge + LIVE/CACHED), component bars (4×), trigger rows (3×)
- Lines 475–516: 20-session history grid (2× `CriHistoryChart`) + `RegimeRelationshipView`

Extract into `web/components/regime/CriSubTab.tsx`. Adaptations:
- Component signature: `export default function CriSubTab({ prices, marketState }: { prices: Record<string, PriceData>; marketState: MarketState })`
- Import path adjustments: every `@/lib/<x>` → `@/lib/regime/<x>`. Sibling `./RegimeStrip`/`./RegimeRelationshipView`/`./CriHistoryChart`/`./InfoTooltip` stay.
- `useRegime(marketState)` from `@/lib/regime/useRegime` — call with `marketState` per the ported hook signature (NOT zero-arg)
- Delete `ShareReportModal` import + `shareModal` JSX + `shareEndpoint`/`shareContentEndpoint`/`shareModalTitle`/`shareButtonTitle`/`shareContentTitle` references (share-to-X out of scope)
- Delete the `dataEndpoint` prop branching (always use the default endpoint via the ported hook)
- Keep `prices` / `marketState` — both fed into `resolveRegimeStripLiveState(prices, data)`. With empty `prices={}` the strip shows all CACHED.
- Keep `SECTION_TOOLTIPS` import (now `@/lib/regime/sectionTooltips`)
- **Keep the "Sync Now" button in the empty state** — wire it to POST `/api/regime/scan` and surface the returned `message` as a toast / banner. The button is part of xenon's UI; for 1:1 mirror it stays. The toast text becomes the existing 202 stub: `"scanner_pending: data sources not yet wired (VIX/VVIX/COR1M)"`. Use the project's existing toast / inline message pattern (search `grep -rn "useToast\|toast\." web/components | head -5` to find it).

Sketch for the Sync Now wiring:

```typescript
const handleSyncClick = async () => {
  try {
    const res = await fetch(`${process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8400"}/api/regime/scan`, { method: "POST" });
    const body = await res.json();
    // Replace with project's toast util; this inline label is a placeholder.
    setSyncMessage(body.message ?? `HTTP ${res.status}`);
  } catch (err) {
    setSyncMessage(err instanceof Error ? err.message : String(err));
  }
};
```

- [ ] **Step 7: Verify it compiles**

Run: `cd web && npx tsc --noEmit`
Expected: No errors. Most likely fixes:
- Missing import for `regimeLiveStrip`, `criCalc`, `criStaleness` — point at `@/lib/regime/<name>`
- `@types/d3` resolution: if d3 functions like `d3.scaleLinear` are typed `any`, ensure `@types/d3` is in `devDependencies` and re-run `npm install`

- [ ] **Step 8: Commit**

```bash
git add web/package.json web/package-lock.json web/components/regime/charts/ web/components/regime/CriSubTab.tsx web/components/regime/CriHistoryChart.tsx web/components/regime/RegimeStrip.tsx web/components/regime/RegimeRelationshipView.tsx
git commit -m "feat(regime): port CRI sub-tab + d3 dep + chart wrappers (strip + hero + history + relationship)"
```

---

## Task 9: VCG sub-tab (visual port)

**Files:**
- Create: `web/components/regime/VcgSubTab.tsx`

- [ ] **Step 1: Port VcgPanel as VcgSubTab**

Copy `/Users/chenxi/projects/xenon/web/components/VcgPanel.tsx` (453 LOC) → `web/components/regime/VcgSubTab.tsx`. Adjust:
- `useVcg` import path → `@/lib/regime/useVcg`
- `useMarketHours` / `MarketState` → `@/lib/regime/useMarketHours`
- `PriceData` → `@/lib/regime/pricesProtocol`
- `InfoTooltip` stays (sibling)
- **Keep** `prices` and `marketState` props — passed from RegimePanel for the eventual live overlay
- **Strip** `ShareReportModal` import + JSX
- Default export name: `VcgSubTab`
- Component signature: `export default function VcgSubTab({ prices, marketState }: { prices: Record<string, PriceData>; marketState: MarketState })`

- [ ] **Step 2: Verify it compiles**

Run: `cd web && npx tsc --noEmit`
Expected: No errors. Fix imports.

- [ ] **Step 3: Commit**

```bash
git add web/components/regime/VcgSubTab.tsx
git commit -m "feat(regime): port VCG sub-tab"
```

---

## Task 10: GEX sub-tab (visual port)

**Files:**
- Create: `web/components/regime/GexSubTab.tsx`
- Create: `web/components/regime/GexProfileChart.tsx`
- Create: `web/components/regime/ui/MetricCard.tsx`

- [ ] **Step 1: Port MetricCard + SourceBadge (required, not optional)**

Copy `/Users/chenxi/projects/xenon/web/components/ui/MetricCard.tsx` → `web/components/regime/ui/MetricCard.tsx`. Both `MetricCard` and `SourceBadge` are named exports used by `GexSubTab`; without them the GEX sub-tab won't compile.

- [ ] **Step 2: Port GexProfileChart**

Copy `/Users/chenxi/projects/xenon/web/components/charts/GexProfileChart.tsx` → `web/components/regime/GexProfileChart.tsx`. Update the `chartSeriesColor` import to `@/lib/regime/chartSystem`.

- [ ] **Step 3: Port GexPanel as GexSubTab**

Copy `/Users/chenxi/projects/xenon/web/components/GexPanel.tsx` (901 LOC) → `web/components/regime/GexSubTab.tsx`. Adjust:
- `useGex` → `@/lib/regime/useGex` (and default it to `"SPX"` to match xenon FastAPI default)
- `useMarketHours` / `MarketState` → `@/lib/regime/useMarketHours`
- `MetricCard, SourceBadge` from `./ui/MetricCard` (sibling, no path change needed since file is at `web/components/regime/ui/MetricCard.tsx`)
- `GexProfileChart` from `./GexProfileChart` (sibling)
- `InfoTooltip` stays (sibling)
- **Keep** `marketState` prop
- **Strip** `ShareReportModal` import + JSX
- Default export name: `GexSubTab`
- Component signature: `export default function GexSubTab({ marketState }: { marketState: MarketState })`

- [ ] **Step 4: Verify it compiles**

Run: `cd web && npx tsc --noEmit`
Expected: No errors. Fix imports.

- [ ] **Step 5: Commit**

```bash
git add web/components/regime/GexSubTab.tsx web/components/regime/GexProfileChart.tsx web/components/regime/ui/
git commit -m "feat(regime): port GEX sub-tab + strike profile chart + MetricCard"
```

---

## Task 11: Wire /regime page route + global styles

**Files:**
- Create: `web/app/regime/page.tsx`
- Modify: `web/app/globals.css` (append `.regime-*` block from xenon)
- Modify: Top-nav component (TBD — verify by reading `web/app/layout.tsx` and the components it pulls in)

- [ ] **Step 1: Create the page route**

Write `web/app/regime/page.tsx`:

```typescript
import RegimePanel from "@/components/regime/RegimePanel";

export const metadata = {
  title: "Regime — Unusual Whales",
  description: "Market-wide regime indicators: CRI, VCG, GEX",
};

export default function RegimePage() {
  return (
    <main className="regime-page">
      <header className="regime-page-header">
        <h1>Regime</h1>
        <p className="regime-page-subtitle">
          Crash Risk Indicator · Vol-Curve Gauge · Gamma Exposure
        </p>
      </header>
      <RegimePanel />
    </main>
  );
}
```

- [ ] **Step 2: Copy regime-specific CSS (@media-aware extraction)**

The xenon CSS isn't contiguous AND many regime-related rules live inside `@media` blocks (responsive layouts at `globals.css:4691-4829`). A naive `\.regime-*\{...\}` regex strips the wrapping `@media` braces and breaks mobile/tablet layouts. Use a CSS parser instead. Install once if needed:

```bash
cd web && npx --yes postcss-cli --version >/dev/null 2>&1 || npm install --no-save postcss postcss-selector-parser
```

Extraction script (handles `@media` + top-level rules):

```bash
XEN=/Users/chenxi/projects/xenon/web/app/globals.css
OUT=/tmp/regime-css.css

node -e '
const fs = require("fs");
const src = fs.readFileSync(process.env.XEN, "utf8");
const PREFIXES = [".regime-", ".cri-", ".vcg-", ".gex-", ".ticker-tab",
  ".section-header", ".section-title", ".metric-card", ".live-badge",
  ".regime-strip", ".regime-relationship", ".regime-history",
  ".regime-component-", ".regime-trigger-", ".regime-hero",
  ".regime-level-badge", ".regime-empty", ".regime-page",
  ".regime-tier-strip", ".regime-badge"];
const SKIP_PREFIXES = [".share-report-modal", ".regime-block-modal"];

function selectorMatches(sel) {
  if (SKIP_PREFIXES.some(p => sel.includes(p))) return false;
  return PREFIXES.some(p => sel.includes(p));
}

// Tokenize on balanced braces. Track depth so @media{...} containing
// matching nested rules survives intact.
let out = [];
let i = 0;
function readRule(depth) {
  const start = i;
  while (i < src.length && src[i] !== "{" && src[i] !== "}") i++;
  if (src[i] !== "{") return null;
  const sel = src.slice(start, i).trim();
  let braces = 1; i++;
  const bodyStart = i;
  while (i < src.length && braces > 0) {
    if (src[i] === "{") braces++;
    else if (src[i] === "}") braces--;
    i++;
  }
  const body = src.slice(bodyStart, i - 1);
  return { sel, body };
}

while (i < src.length) {
  while (i < src.length && /\s/.test(src[i])) i++;
  if (i >= src.length) break;
  if (src.slice(i, i + 7) === "@media ") {
    const r = readRule(0);
    if (r) {
      // Recurse into @media body to filter inner rules
      const inner = (function () {
        let j = 0, kept = [];
        const inner = r.body;
        while (j < inner.length) {
          while (j < inner.length && /\s/.test(inner[j])) j++;
          const s0 = j;
          while (j < inner.length && inner[j] !== "{" && inner[j] !== "}") j++;
          if (inner[j] !== "{") break;
          const sel = inner.slice(s0, j).trim();
          let br = 1; j++; const bodyS = j;
          while (j < inner.length && br > 0) {
            if (inner[j] === "{") br++;
            else if (inner[j] === "}") br--;
            j++;
          }
          if (selectorMatches(sel)) kept.push(`  ${sel} {${inner.slice(bodyS, j - 1)}}`);
        }
        return kept.join("\n");
      })();
      if (inner.trim()) out.push(`${r.sel} {\n${inner}\n}`);
    }
  } else {
    const r = readRule(0);
    if (r && selectorMatches(r.sel)) out.push(`${r.sel} {${r.body}}`);
  }
}
fs.writeFileSync(process.env.OUT, out.join("\n\n"));
console.log(`Extracted ${out.length} rules`);
' && head -5 "$OUT"
```

Then append the contents of `/tmp/regime-css.css` to `web/app/globals.css` under a marker comment:

```css
/* ─── Regime panel (ported from xenon 2026-05-16) ───────────────────── */
/* contents of /tmp/regime-css.css */
```

After appending, review for selectors that depend on `--chart-live-badge-bg`, `--chart-live-badge-text`, or other CSS custom properties not defined here. For any missing var: add to `:root` near other Argon tokens OR substitute an existing token (`var(--accent)`, `var(--positive)`, `var(--text-muted)`).

(Selectors for `ShareReportModal`/`RegimeBlockModal` are skipped automatically by the script's `SKIP_PREFIXES`.)

- [ ] **Step 3: Add /regime to the Sidebar nav (verified location)**

The nav is at `web/components/shared/Sidebar.tsx` — a `NAV` array near the top. Add an entry:

```diff
 import { LayoutDashboard, Radar, ScanLine } from "lucide-react";
+import { Activity } from "lucide-react";  // or another suitable icon
 import { HealthPanel } from "./HealthPanel";

 const NAV = [
   { href: "/", label: "Dashboard", icon: LayoutDashboard },
   { href: "/scanner", label: "Scanner", icon: ScanLine },
   { href: "/cockpit/SPY", label: "Cockpit", icon: Radar },
+  { href: "/regime", label: "Regime", icon: Activity },
 ];
```

(Pick `Activity` or another `lucide-react` icon — `BarChart3`, `Gauge`, `Signal`, etc. all fit. Confirm the icon is in `lucide-react` by running `node -e "console.log(Object.keys(require('lucide-react')).slice(0,5))"` from `web/`.)

- [ ] **Step 4: Verify page renders**

Run dev server: `bash scripts/dev.sh`
Navigate to `http://localhost:3001/regime`.
Expected:
- Sidebar shows the new Regime link
- Page renders with title "Regime"
- Three tab buttons: CRI / VCG / GEX
- Default tab (CRI) shows the empty-state "No CRI data available. Click Sync Now to run a scan."
- Sync Now button is present and clickable; clicking it surfaces the 202 stub message ("scanner_pending: ...")
- Clicking VCG / GEX swaps content; each shows empty-state placeholder
- No console errors (in particular, no `d3 is not defined` or `Cannot read properties of undefined (reading 'profile')`)

Stop the dev server (Ctrl+C).

- [ ] **Step 5: Commit**

```bash
git add web/app/regime/ web/app/globals.css web/components/shared/Sidebar.tsx
git commit -m "feat(regime): /regime page route + Sidebar nav link + ported styles"
```

---

## Task 12: Vitest + Playwright smoke tests

**Files:**
- Create: `web/tests/unit/regime-page.test.tsx`
- Create: `web/tests/e2e/regime-page.spec.ts`

- [ ] **Step 1: Write Vitest component test**

Write `web/tests/unit/regime-page.test.tsx`:

```typescript
import { describe, it, expect, beforeEach, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import RegimePanel from "@/components/regime/RegimePanel";

// Mock all 3 regime endpoints with empty-state payloads matching the EMPTY_*_RESPONSE
// shapes in src/uw_scan/api/schemas.py. The ported VcgPanel + GexPanel destructure
// fields like `signal.attribution`, `data.profile`, `data.bias` — they must be present.
beforeEach(() => {
  const empty = {
    cri: {
      scan_time: "", date: "", market_open: false,
      vix: null, vvix: null, spy: null,
      vix_5d_roc: null, vvix_vix_ratio: null, spx_100d_ma: null,
      spx_distance_pct: null, cor1m: null, cor1m_previous_close: null,
      cor1m_5d_change: null, realized_vol: null,
      cri: { score: 0, level: "LOW", components: { vix: 0, vvix: 0, correlation: 0, momentum: 0 } },
      cta: { realized_vol: 0, exposure_pct: 200, forced_reduction_pct: 0, est_selling_bn: 0 },
      menthorq_cta: null,
      crash_trigger: { triggered: false, conditions: { spx_below_100d_ma: false, realized_vol_gt_25: false, cor1m_gt_60: false }, values: {} },
      history: [], spy_closes: [],
    },
    vcg: {
      scan_time: "", market_open: false, credit_proxy: null,
      signal: {
        vcg: null, vcg_adj: null, residual: null, beta1_vvix: null, beta2_vix: null,
        alpha: null, vix: null, vvix: null, credit_price: null, credit_5d_return_pct: null,
        ro: null, edr: null, tier: null, bounce: null, vvix_severity: null,
        sign_ok: null, sign_suppressed: null, pi_panic: null, regime: null, interpretation: null,
        attribution: { vvix_pct: null, vix_pct: null, vvix_component: null, vix_component: null, model_implied: null },
      },
      history: [],
    },
    gex: {
      scan_time: "", market_open: false, ticker: "SPX",
      spot: null, close: null, day_change: null, day_change_pct: null, data_date: null,
      net_gex: null, net_dex: null, atm_iv: null, vol_pc: null,
      levels: { gex_flip: null, max_magnet: null, second_magnet: null, max_accelerator: null, put_wall: null, call_wall: null },
      profile: [],
      expected_range: { low: null, high: null, iv_1d: null },
      bias: { direction: null, reasons: [], days_above_flip: null, flip_migration: [] },
      history: [], iv: null, mq: null, source_delta: null,
    },
  };
  vi.stubGlobal("fetch", vi.fn((url: string) => {
    const u = String(url);
    let body: object = empty.cri;
    if (u.includes("/regime/vcg")) body = empty.vcg;
    else if (u.includes("/regime/gex")) body = empty.gex;
    return Promise.resolve({ ok: true, json: async () => body });
  }));
});

describe("RegimePanel", () => {
  it("renders three sub-tab buttons", () => {
    render(<RegimePanel />);
    expect(screen.getByTestId("regime-tab-cri")).toHaveTextContent("CRI");
    expect(screen.getByTestId("regime-tab-vcg")).toHaveTextContent("VCG");
    expect(screen.getByTestId("regime-tab-gex")).toHaveTextContent("GEX");
  });

  it("swaps to VCG tab on click", () => {
    render(<RegimePanel />);
    fireEvent.click(screen.getByTestId("regime-tab-vcg"));
    expect(screen.getByTestId("regime-tab-vcg")).toHaveClass("active");
  });

  it("swaps to GEX tab on click", () => {
    render(<RegimePanel />);
    fireEvent.click(screen.getByTestId("regime-tab-gex"));
    expect(screen.getByTestId("regime-tab-gex")).toHaveClass("active");
  });
});
```

- [ ] **Step 2: Run Vitest**

Run: `cd web && npm run test -- regime-page`
Expected: 3 PASSED.

- [ ] **Step 3: Write Playwright smoke test**

Write `web/tests/e2e/regime-page.spec.ts`:

```typescript
import { test, expect } from "@playwright/test";

test("/regime renders with three sub-tabs and an empty CRI state", async ({ page }) => {
  await page.goto("/regime");
  await expect(page.getByRole("heading", { name: "Regime" })).toBeVisible();
  await expect(page.getByTestId("regime-tab-cri")).toBeVisible();
  await expect(page.getByTestId("regime-tab-vcg")).toBeVisible();
  await expect(page.getByTestId("regime-tab-gex")).toBeVisible();
  await expect(page.getByText(/No CRI data available/i)).toBeVisible();
});

test("clicking VCG and GEX swaps the active tab", async ({ page }) => {
  await page.goto("/regime");
  await page.getByTestId("regime-tab-vcg").click();
  await expect(page.getByTestId("regime-tab-vcg")).toHaveClass(/active/);
  await page.getByTestId("regime-tab-gex").click();
  await expect(page.getByTestId("regime-tab-gex")).toHaveClass(/active/);
});
```

- [ ] **Step 4: Run Playwright**

Run: `cd web && npx playwright test regime-page`
Expected: 2 PASSED.

- [ ] **Step 5: Commit**

```bash
git add web/tests/unit/regime-page.test.tsx web/tests/e2e/regime-page.spec.ts
git commit -m "test(regime): vitest + playwright smoke for /regime page"
```

---

## Task 13: PR

- [ ] **Step 1: Create branch + PR**

```bash
git checkout -b feat/regime-skeleton-port
git push -u origin feat/regime-skeleton-port
gh pr create --title "feat(regime): port /regime skeleton from xenon (CRI/VCG/GEX)" --body "$(cat <<'EOF'
## Summary
- Mirrors xenon's /regime top-level page with three sub-tabs: CRI, VCG, GEX
- Adds DB tables (cri_series, vcg_series, gex_snapshots) and FastAPI endpoints (/api/regime, /api/regime/scan, /api/regime/vcg, /api/regime/gex)
- Endpoints return empty/null payloads in the exact shape xenon's frontend expects; tables stay empty until backfill phase wires VIX/VVIX/COR1M/SPY sources
- /scan endpoint is a 202 stub — scanner ports come in a follow-up plan

## Out of scope
- Scanner internals (cri.py / vcg.py / gex.py — ~3700 LOC)
- Data source wiring (IB Gateway, FMP, Cboe COR1M scraper)
- regime_overrides table + governance gate (xenon-specific, not part of the three sub-tabs)
- Share-to-X social posting

## Test plan
- [x] `uv run pytest tests/integration/api/test_regime_router.py tests/integration/test_regime_repository.py tests/unit/test_regime_schemas.py`
- [x] `cd web && npm run test -- regime-page`
- [x] `cd web && npx playwright test regime-page`
- [x] Manual: `/regime` route renders, all 3 tabs swap, empty state shown
EOF
)"
```

---

## Backfill phase (separate plan — outline only)

Once this skeleton lands, the backfill plan will need to:
1. **Pick data sources for VIX, VVIX, COR1M** — three options:
   - Cboe direct dashboard URL (free, narrow — xenon already has a scraper for COR1M only)
   - FMP API (paid, broad — adds new dependency)
   - Polygon / Tradier / etc.
2. **Add SPY OHLC backfill from massive** (already in this repo)
3. **Port xenon's CRI scoring formula** from `src/xenon/scanners/cri.py` into a much smaller `src/uw_scan/cards/regime_cri.py` (skip the IB/Yahoo plumbing — just the math + DB write)
4. **Wire APScheduler job** in `src/uw_scan/worker/scheduler.py` to call the scanner every N minutes
5. **VCG and GEX** are larger scanners — likely separate plans each

This is intentionally not scoped here; the user said "then we can think about backfill the data."

---

## Self-review notes

- All file paths are absolute or repo-relative.
- Each code-bearing step shows the actual code (no `# TODO`).
- The "copy from xenon" steps for large components do not inline 500+ lines but DO list specific imports to adjust and props to strip — the executor has a deterministic checklist.
- Empty-state handling is the cornerstone: with no data wired, every panel falls back to the existing "No data" branch the xenon code already has.
- Tests verify shape (backend) and rendering + tab nav (frontend) — both are independent of data presence.
