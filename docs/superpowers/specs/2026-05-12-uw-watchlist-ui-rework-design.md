# UW Scanner — Watchlist UI Rework (Design Spec)

**Status:** Draft for review
**Author:** brainstorming session, 2026-05-12
**Supersedes:** `docs/superpowers/archive/specs/2026-05-11-uw-scan-design.md` (S1/S2 Streamlit-era contracts; archived as historical reference for the report-content semantics, which this spec still honours at the model layer)
**Companion notes:**
- `docs/superpowers/research/2026-05-12-spec-pct-and-skew-dte-research.md` (defines Aggression % + skew DTE constants used below)

---

## 1. Goals

Replace the existing Streamlit prototype (`app/streamlit_app.py`, `app/views/`) with a Next.js + FastAPI two-tier application that:

1. Renders a **card-grid watchlist** as the landing page — modelled on the Market Pulse reference (`docs/card ui example.JPG`) but using the project's own terminology and data model.
2. Drills into a **regime-style detail page** per ticker, rendering the existing `SingleStockReport` content across tabbed sections.
3. Keeps the **Python pipeline (`src/uw_scan/`) intact** — pipeline, repository, API client, normalisers, scoring, and the canonical S1/S2 report shapes are framework-agnostic and remain authoritative. New work is additive (`api/`, `worker/`, OHLC provider, `watchlist_card` denorm).
4. Persists watchlist state and cached card data in Postgres (`option_wizard`, schema `uw_scan`); UI is **read-only browse** of that cache, refreshed by an out-of-process scheduler.
5. Supports **full CRUD on the watchlist** (add/remove/edit/pin/reorder) from the UI.

Streamlit is retired in this rework — no parity gate, no dual-run, no migration period.

## 2. Non-goals

- **Real-time streaming.** No WebSockets, no SSE for v1. Server-component fetch + client-polled rescan jobs are sufficient.
- **Multi-user / auth.** Single-user local-host tool, mirrors `xenon` and `apex` deployment model. No Clerk, no session state.
- **Mobile-first.** Responsive grid down to single-column at narrow widths is fine, but the design target is wide-screen desktop (≥1440px).
- **Theme toggle.** Dark mode only. The Market Pulse reference, xenon's design system, and the screen-density requirements all assume dark.
- **Backwards compatibility** with persisted Streamlit-era run rows (rows in `scan_runs` written before the schema additions are still readable — new fields default null — but no UI re-renders them in the old layout).

## 3. Architecture

```
┌─ FRONTEND (web/) ──────────────────┐
│  Next.js 16 + React 19             │
│  Tailwind 3.4                      │
│  IBM Plex Mono + Inter (fonts)     │   →  fetch  →  ┌─ FASTAPI (src/uw_scan/api/) ──┐
│  /watchlist   landing card grid    │                │  /api/watchlist                │
│  /stock/[t]   detail card + tabs   │                │  /api/stock/{ticker}           │
│  /admin       ops page             │                │  /api/ohlc/{ticker}            │
│  Design tokens copied from xenon   │                │  (read-only, all GET)          │
└────────────────────────────────────┘                │  + CRUD on watchlist           │
                                                      │  + rescan job enqueue          │
                                                      └────────┬───────────────────────┘
                                                               │ reads/writes
┌─ WORKER (src/uw_scan/worker/) ─────┐                  ┌──────▼───────────────┐
│  APScheduler in own process        │  ── writes ──→   │  Postgres            │
│  RTH spot-refresh (cron)           │                  │  option_wizard       │
│  RTH-hourly + EOD UW scan          │                  │  schema: uw_scan     │
│  Daily massive.io OHLC pull        │                  └──────────────────────┘
│  Ad-hoc rescan poller              │
│  Imports run_single_stock as-is    │
└────────────────────────────────────┘
```

**Three processes, run concurrently in dev** via a `concurrently`-style script (mirrors `xenon/web/package.json`'s `dev` script):

| Process | Port | Source | Reload on |
|---|---|---|---|
| `next dev` | 3000 | `web/` | TS/TSX file change |
| `uvicorn uw_scan.api.server:app --reload` | 8400 | `src/uw_scan/api/` | Python file change in `src/` |
| `python -m uw_scan.worker.scheduler` | n/a | `src/uw_scan/worker/` | manual restart |

The scheduler is **deliberately a separate process** from FastAPI: it can crash and restart independently, its long jobs don't share the request lifecycle, and its tick rate isn't tied to HTTP traffic.

Streamlit entry point and views are deleted entirely. The `streamlit` dependency is removed from `pyproject.toml`.

## 4. Data model

All new structures live in `uw_scan` schema. Migrations follow the existing convention in `src/uw_scan/storage/migrations/` (`001_s1_core_tables.sql`, `002_s2_scan_tables.sql` already present). New files for this rework: `003_watchlist_tables.sql`, `004_strike_gex_curve.sql`, `005_jobs_table.sql`, `006_seed_watchlist.sql`.

### 4.1 New tables

```sql
-- 4.1.1 Canonical watchlist (DB is source of truth; JSON is initial seed only)
CREATE TABLE uw_scan.watchlist (
  ticker        TEXT PRIMARY KEY,
  sector        TEXT NOT NULL,                 -- "Technology", "Financials", "ETF", ...
  notes         TEXT,                          -- free-form, from JSON 'notes' seed
  pinned        BOOLEAN NOT NULL DEFAULT FALSE,
  sort_rank     INTEGER NOT NULL DEFAULT 0,    -- user-controlled order within sector
  added_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  removed_at    TIMESTAMPTZ                    -- soft delete; NULL = active
);
CREATE INDEX idx_watchlist_active
  ON uw_scan.watchlist (sector, sort_rank)
  WHERE removed_at IS NULL;

-- 4.1.2 Latest denormalised card row per ticker (the grid payload)
CREATE TABLE uw_scan.watchlist_card (
  ticker            TEXT PRIMARY KEY REFERENCES uw_scan.watchlist(ticker),
  run_id            BIGINT NOT NULL REFERENCES uw_scan.scan_runs(run_id)
                       ON DELETE RESTRICT,     -- card row is meaningless without its source run
  scanned_at        TIMESTAMPTZ NOT NULL,      -- when the full UW scan ran
  spot              NUMERIC(18,4),
  spot_quoted_at    TIMESTAMPTZ,               -- when 'spot' was sourced (~15m delayed)
  spot_source       TEXT,                      -- 'uw_scan' | 'massive.io_intraday'

  -- Header
  iv_atm            NUMERIC(8,4),              -- decimal, e.g. 0.293 = 29.3%
  iv_rank           NUMERIC(6,2),              -- 0..100

  -- Setup badge
  setup_type        TEXT,                      -- 'C' | 'F' | NULL
  setup_direction   TEXT,                      -- 'bull' | 'bear' | NULL
  setup_score       NUMERIC(8,4),

  -- Aggression gauge: ask_side_premium / (ask_side + bid_side)
  aggression_pct    NUMERIC(6,4),

  -- Returns (from daily_ohlc + intraday_quote)
  ret_1d            NUMERIC(8,4),
  ret_1w            NUMERIC(8,4),
  ret_30d           NUMERIC(8,4),

  -- GAMMA block
  gex_flip_distance NUMERIC(8,4),              -- (flip_price - spot) / spot
  gex_flip_price    NUMERIC(18,4),
  gex_per_1pct_move NUMERIC(18,2),             -- net_gex * 0.01 * spot
  max_gex_strike    NUMERIC(18,4),
  gex_expiring_pct  NUMERIC(8,4),              -- share of |GEX| at nearest expiry
  gex_expiring_date DATE,

  -- SKEW (30 DTE, 25-delta risk reversal — see research note)
  skew_25d_30dte    NUMERIC(8,4),

  -- POSITIONING
  call_oi_total     BIGINT,
  put_oi_total      BIGINT,
  pcr_oi            NUMERIC(8,4),
  pcr_vol           NUMERIC(8,4),
  pcr_delta_30d     NUMERIC(8,4),              -- pcr_oi(today) - pcr_oi(30d-prior snapshot)

  updated_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 4.1.3 Daily OHLC cache (massive.io is the v1 provider)
CREATE TABLE uw_scan.daily_ohlc (
  ticker     TEXT NOT NULL,
  date       DATE NOT NULL,
  open       NUMERIC(18,4),
  high       NUMERIC(18,4),
  low        NUMERIC(18,4),
  close      NUMERIC(18,4) NOT NULL,
  volume     BIGINT,
  source     TEXT NOT NULL,                    -- 'massive.io' for v1
  fetched_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  PRIMARY KEY (ticker, date)
);
CREATE INDEX idx_ohlc_recent
  ON uw_scan.daily_ohlc (ticker, date DESC);

-- 4.1.4 Intraday quote (rolling, one row per ticker)
CREATE TABLE uw_scan.intraday_quote (
  ticker     TEXT PRIMARY KEY REFERENCES uw_scan.watchlist(ticker),
  price      NUMERIC(18,4) NOT NULL,
  quoted_at  TIMESTAMPTZ NOT NULL,             -- massive.io's timestamp
  fetched_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 4.1.5 PCR daily snapshot (for true 30d delta)
CREATE TABLE uw_scan.pcr_history (
  ticker        TEXT NOT NULL,
  snapshot_date DATE NOT NULL,
  pcr_oi        NUMERIC(8,4),
  pcr_vol       NUMERIC(8,4),
  PRIMARY KEY (ticker, snapshot_date)
);

-- 4.1.6 Ad-hoc rescan jobs (poll-based progress for the Rescan button)
CREATE TABLE uw_scan.jobs (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  ticker        TEXT NOT NULL REFERENCES uw_scan.watchlist(ticker),
  status        TEXT NOT NULL,                 -- 'queued' | 'running' | 'done' | 'failed'
  run_id        BIGINT,                        -- populated when done
  error         TEXT,
  requested_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  started_at    TIMESTAMPTZ,
  finished_at   TIMESTAMPTZ
);
CREATE INDEX idx_jobs_queued
  ON uw_scan.jobs (status, requested_at)
  WHERE status IN ('queued','running');
```

### 4.2 Existing-table additions

```sql
-- Persist the per-strike GEX curve so card-row derivation can compute the flip
-- point and max-GEX strike, and the detail page can render the GEX chart from
-- the same source.
ALTER TABLE uw_scan.scan_runs
  ADD COLUMN strike_gex_curve JSONB;           -- nullable; old rows stay valid
```

Old `scan_runs` rows survive untouched. New fields default to NULL; the card-derivation function returns NULL for downstream fields when their inputs are missing.

### 4.3 Watchlist seed

The 54-ticker JSON pasted in the brainstorming session is stored in-repo at `data/watchlist_seed.json`. A one-shot migration (`src/uw_scan/storage/migrations/006_seed_watchlist.sql` — numbering continues from the planned `003`–`005` sequence above) inserts rows. After that, the JSON is **reference only** — DB is canonical.

## 5. API surface

FastAPI, mounted at `/api/*`. No auth. Returns Pydantic-modelled JSON throughout. OpenAPI schema is auto-generated and consumed by the frontend via `openapi-typescript` to produce `lib/types.ts`.

```
GET    /api/health                            → { ok, db, scheduler_lag_seconds }
GET    /api/watchlist                         → grid payload (one round-trip for all cards)
       ?sector=Technology                       optional filters; combinable
       &setup=C-bull
       &fresh_within_minutes=60
GET    /api/stock/{ticker}                    → full SingleStockReport (latest run)
GET    /api/stock/{ticker}/runs               → [{ run_id, scanned_at }]
GET    /api/stock/{ticker}/runs/{run_id}      → specific past report
GET    /api/ohlc/{ticker}?days=90             → daily_ohlc rows for sparkline / charts

POST   /api/watchlist                         → add ticker { ticker, sector, notes? }
DELETE /api/watchlist/{ticker}                → soft-delete (sets removed_at)
PATCH  /api/watchlist/{ticker}                → edit notes/sector/pinned/sort_rank

POST   /api/watchlist/{ticker}/rescan         → enqueue rescan; returns { job_id }
GET    /api/jobs/{job_id}                     → { status, run_id?, error? }
```

### 5.1 Watchlist grid payload shape

```jsonc
{
  "scanned_at_min": "2026-05-12T13:01:23Z",
  "scanned_at_max": "2026-05-12T13:04:11Z",
  "scheduler_lag_seconds": 47,
  "tickers": [
    {
      "ticker": "TSLA",
      "sector": "Consumer Discretionary",
      "pinned": false,
      "spot": 445.12,
      "spot_quoted_at": "2026-05-12T13:07:55Z",
      "spot_source": "massive.io_intraday",
      "scanned_at": "2026-05-12T13:01:23Z",
      "iv_atm": 0.691,
      "iv_rank": 39.0,
      "setup": { "type": "C", "direction": "bear", "score": 1.51 },
      "aggression_pct": 0.91,
      "returns":  { "d1": -0.044, "w1": 0.016, "d30": 0.054 },
      "gamma":    { "flip_distance": -0.075, "flip_price": 411.50,
                    "per_1pct_move": -1940000, "max_strike": 420.0,
                    "expiring_pct": 0.482, "expiring_date": "2026-05-15" },
      "skew":     { "rr25d_30dte": -0.0146 },
      "positioning": { "call_oi": 1200000, "put_oi": 2100000,
                       "pcr_oi": 1.75, "pcr_vol": 1.58, "pcr_delta_30d": -0.03 }
    }
    // ...one entry per active watchlist ticker
  ]
}
```

The grid loads in **one server-side fetch**. The Next.js `/watchlist` page is a server component, so the populated HTML hits the browser without a client-side loading state.

### 5.2 Rescan flow (async polling)

```
User clicks Rescan on TSLA card
        ↓ POST /api/watchlist/TSLA/rescan
        ↓ insert jobs row { status: 'queued', ticker: 'TSLA' }
        ↓ return { job_id }
Frontend polls GET /api/jobs/{job_id} every 1000 ms
Scheduler worker's ad-hoc-job loop (1s tick) picks up queued rows,
  marks them 'running', runs run_single_stock(ticker), writes
  scan_runs row, recomputes watchlist_card row, sets
  jobs.status='done' + jobs.run_id=...
Frontend sees status='done' → calls router.refresh() → server component
  re-fetches /api/watchlist → grid updates in place
```

## 6. Frontend structure

### 6.1 Stack (locked to xenon's choices for muscle-memory consistency)

- Next.js 16 (App Router) + React 19
- Tailwind CSS 3.4
- IBM Plex Mono (numbers) + Inter (labels) via `@fontsource/*`
- Zero state library for v1 — server components + URL state + local React state for the rescan island
- `openapi-typescript` for generated types from FastAPI OpenAPI
- `lucide-react` icons (matches xenon)
- No Clerk (single-user local)

### 6.2 Routes

```
/                          → redirect to /watchlist
/watchlist                 → server component, one fetch to /api/watchlist
  ?sector=Technology       → filter chips encode state in URL
  &setup=C-bull
  &fresh=60                → only show cards scanned <60 min ago
/stock/[ticker]            → redirects to /stock/[ticker]/market-structure
/stock/[ticker]/[tab]      → tab as a dynamic URL segment with a runtime whitelist
                             (single page.tsx file; if params.tab not in
                             {market-structure, volatility, flow, vrp,
                              trade-plan, tables} → notFound()).
                             Bookmark-able; browser back/forward steps per tab
/admin                     → ops page: scheduler status, last 20 runs,
                             "Add ticker", "Rescan all stale"
```

### 6.3 Component tree

```
app/
  layout.tsx                       # html shell, global CSS, font preload
  page.tsx                         # redirect → /watchlist
  watchlist/
    page.tsx                       # server component, fetches /api/watchlist
    loading.tsx                    # skeleton grid
  stock/
    [ticker]/
      layout.tsx                   # detail header strip + tab nav (persists)
      page.tsx                     # redirect to /market-structure
      [tab]/page.tsx               # one tab body
  admin/page.tsx

components/
  watchlist/
    CardGrid.tsx                   # client wrapper: responsive grid + sector groups
    TickerCard.tsx                 # one card (the Market-Pulse-style block)
    CardHeader.tsx                 # ticker + IV ATM + IVR + freshness + ⋯ menu
    SetupBadge.tsx                 # NEUTRAL / C-BULL / C-BEAR / F-MULTI pills
    SparklineRow.tsx               # SVG sparkline + 1d/1w/30d return chips
    AggressionGauge.tsx            # circular gauge for aggression_pct
    GammaBlock.tsx                 # GEX flip / 1%-move / max-strike / expiring
    SkewBlock.tsx                  # 25Δ RR @ 30 DTE
    PositioningBlock.tsx           # OI split bar + PCR triplet
    FilterBar.tsx                  # sector chips, setup chips, freshness slider
    AddTickerDialog.tsx            # modal for POST /api/watchlist

  stock/
    DetailHeader.tsx               # ticker, spot, setup verdict, freshness, ⋯
    TabBar.tsx                     # 6 tabs, active state, URL-driven
    tabs/
      MarketStructureTab.tsx
      VolatilityTab.tsx
      FlowTab.tsx
      VrpTab.tsx
      TradePlanTab.tsx
      TablesTab.tsx
    panels/
      MetricGrid.tsx               # generic 4-col label+value grid
      MetricRow.tsx                # one row inside a panel
      DataTable.tsx                # OI changes, alerts, legs, max_pain_rows
      GexChart.tsx                 # SVG/D3 per-strike GEX with flip line

  shared/
    InfoTooltip.tsx                # copied from xenon
    LiveBadge.tsx                  # copied from xenon, our freshness logic
    NumericValue.tsx               # tabular-nums + sign-colour + null='—'
    RescanButton.tsx               # the only client-polling island

lib/
  api.ts                           # typed fetch wrappers; cache: 'no-store'
  formatters.ts                    # fmtPct, fmtMoney, fmtSigned (port of xenon's)
  types.ts                         # generated from FastAPI OpenAPI
  freshness.ts                     # bucket scanned_at → fresh / stale / dead
```

### 6.4 Design tokens

`web/app/globals.css` copies xenon's `:root` + `[data-theme="dark"]` token blocks verbatim. Key tokens:

```css
--bg-base: #0a0f14;
--bg-panel: #0f1519;
--bg-panel-raised: #151c22;
--border-dim: #1e293b;
--text-primary: #e2e8f0;
--text-secondary: #94a3b8;
--text-muted: #475569;
--positive: #05ad98;
--negative: #e85d6c;
--warning: #f5a623;
--info: #8b5cf6;
--font-sans: "Inter", -apple-system, sans-serif;
--font-mono: "IBM Plex Mono", monospace;
```

**Setup badge colour mapping** (canonical for the project):

| Setup state | Label | Colour |
|---|---|---|
| `setup_type='C'`, `direction='bull'` | **C-BULL** | `--positive` |
| `setup_type='C'`, `direction='bear'` | **C-BEAR** | `--negative` |
| `setup_type='F'` | **F-MULTI** | `--info` |
| no setup | **NEUTRAL** | `--text-muted` |

### 6.5 Data-fetching pattern

- **Watchlist landing**: server component, `await fetch(API + '/watchlist', { cache: 'no-store' })`. No client-side data fetching. Filter state in URL → server re-renders on navigation.
- **Detail page**: each tab's `page.tsx` is a server component that fetches `/api/stock/{ticker}` via a shared loader `getStockReport(ticker)` wrapped in `react.cache()` (Next.js App Router does **not** pass a layout's fetched data into child page components, so each tab page is responsible for its own fetch). The `react.cache()` wrapper dedupes the call within a single render pass; cross-navigation tab swaps DO re-fetch — this is acceptable because FastAPI is on localhost (sub-10ms reads) and the scheduler is the freshness layer. If round-trip latency becomes a concern, promote `getStockReport` to a `unstable_cache`-backed loader with a short TTL.
- **Rescan polling**: only client-side fetch in the app. `useEffect` + `setInterval` + `router.refresh()` on completion. No SWR / React Query.
- All `fetch()` to FastAPI uses `cache: 'no-store'`. The scheduler is the cache layer; Next.js's default `fetch` deduplication would mask fresh writes.

## 7. Card field-mapping contract

Each `watchlist_card` row is derived after every full UW scan via a pure function:

```python
def compute_watchlist_card_row(
    report: SingleStockReport,
    ohlc_history: list[OhlcRow],         # most recent ~40 trading days
    intraday: IntradayQuote | None,
    prev_pcr_30d: PcrHistoryRow | None,
    strike_gex_curve: list[StrikeGexRow],
) -> WatchlistCardRow: ...
```

Each output field is defined by exactly one source. **Null is preserved end-to-end** — a missing input never becomes a fabricated zero.

| Field | Source | Computation | Null when |
|---|---|---|---|
| `spot` | `intraday.price` ?? `report.market_structure.spot` | direct | both missing |
| `spot_quoted_at`, `spot_source` | `intraday` if used, else scan timestamp | direct | n/a |
| `iv_atm` | `report.volatility.iv` | direct | UW returns null |
| `iv_rank` | `report.volatility.iv_rank` | direct | < 1y of UW IV history |
| `setup_*` | `report.setup` | direct (badge label derived in UI) | no setup classification |
| `aggression_pct` | `report.flow` | `ask_side_premium / (ask_side + bid_side)` | denominator = 0 |
| `ret_1d` | `intraday.price`, `ohlc_history[-1].close` | `(price - prev_close) / prev_close` | < 1 OHLC row |
| `ret_1w` | `intraday.price`, `ohlc_history[-5]` | `(price - close[-5]) / close[-5]` (price = current; close[-5] = close 5 trading days ago) | < 5 rows |
| `ret_30d` | `intraday.price`, `ohlc_history[-21]` | `(price - close[-21]) / close[-21]` (~1 month) | < 21 rows |

All three returns use the **current intraday price** as the numerator, so they reflect today's intraday move in addition to the historical lookback. They are therefore all recomputed in the **spot-refresh** job (not just `ret_1d`).
| `gex_flip_price` | `strike_gex_curve` | strike where cumulative GEX (sorted asc by strike) changes sign | flat curve / single sign |
| `gex_flip_distance` | derived | `(flip_price - spot) / spot` | flip null |
| `gex_per_1pct_move` | `report.market_structure.net_gex`, `spot` | `net_gex * 0.01 * spot` | either null |
| `max_gex_strike` | `strike_gex_curve` | `argmax(\|net_gex\|)` over strikes | empty curve |
| `gex_expiring_pct` | `strike_gex_curve` bucketed by expiry | `\|net_gex@nearest_exp\| / sum(\|net_gex_by_expiry\|)` (denominator is sum of absolute values, never zero unless every bucket is exactly zero) | empty curve, **or** sum-of-absolutes = 0 (no GEX anywhere) |
| `gex_expiring_date` | `strike_gex_curve` | nearest expiry present | empty curve |
| `skew_25d_30dte` | `report.volatility.skew_25d` | direct, **with S0 verification** | UW returns null |
| `call_oi_total`, `put_oi_total` | `report` (to be exposed from `BulkScreenerRow.call_open_interest` / `put_open_interest`) | direct | UW returns null |
| `pcr_oi` | `put_oi_total / call_oi_total` | direct | either null / call=0 |
| `pcr_vol` | call/put volume totals (already in `BulkScreenerRow`) | `put_volume / call_volume` | either null / call=0 |
| `pcr_delta_30d` | `pcr_oi` today, `pcr_history` 30 cal. days ago | `today - then` | < 30d history |

### 7.1 Aggression % definition

**`aggression_pct = ask_side_premium / (ask_side_premium + bid_side_premium)`**

- Range: 0..1. Rendered as a circular gauge with the rounded integer percent in the centre.
- Label on the card: **"FLOW AGGR."** — not "Spec %". The metric measures ask-side aggression on resting quotes, not "speculation" in any defined sense.
- Rationale and rejected alternatives recorded in `docs/superpowers/research/2026-05-12-spec-pct-and-skew-dte-research.md`.

### 7.2 Skew DTE constant

**`SKEW_TARGET_DTE_DAYS = 30`** (defined in `uw_scan.config`).

- Uses the existing `volatility.skew_25d` field on `SingleStockReport`.
- **S0 verification required:** confirm what DTE the current pipeline picks for `skew_25d`. The raw `SkewRow` carries per-expiry 25Δ RR, so the pipeline picks one. If it isn't already 30-day, normalise during S0.
- Rationale (25Δ RR is the industry-standard skew measurement): see the research note.

### 7.3 What we get from `BulkScreenerRow` for free

Found while writing this spec: `BulkScreenerRow` (already populated by the S2 pipeline) carries fields we previously thought required new pipeline work:

- `call_volume_ask_side` / `bid_side`, `put_volume_ask_side` / `bid_side` — ask-side flow at the contract level
- `call_open_interest` / `put_open_interest` — call/put OI totals
- `call_volume` / `put_volume` — today's call/put volume
- `put_call_ratio` — PCR, ready-made
- `iv30d`, `iv30d_1d`, `iv30d_1w`, `iv30d_1m` — 30d ATM IV + changes
- `gex_net_change`, `gex_ratio`, `gex_perc_change` — gamma deltas

S1 currently fetches a subset of these for its `SingleStockReport`; the pipeline change in §9 is to **also fetch the per-ticker bulk-screener row** during S1 deep-dives and expose the relevant aggregates on the model. This replaces ~half the previously-planned pipeline extensions.

## 8. Scheduler design

APScheduler running in a dedicated worker process (`python -m uw_scan.worker.scheduler`). Three configurable jobs plus one ad-hoc-rescan loop.

### 8.1 Jobs

| Job | Trigger (default) | What it does | UW cost |
|---|---|---|---|
| **Spot refresh** | every `UW_SCAN_SPOT_REFRESH_SECONDS` (default 300, RTH only) | Fetch massive.io intraday quote for every active watchlist ticker. Upsert `intraday_quote`. Recompute spot-derived `watchlist_card` fields: `spot`, `spot_quoted_at`, `spot_source`, `ret_1d`, `ret_1w`, `ret_30d`, `gex_per_1pct_move`, `gex_flip_distance` | none |
| **Full scan** | `UW_SCAN_FULL_SCAN_CRON` (default `*/60 9-16 * * 1-5` ET, plus `15 16 * * 1-5` EOD) | For every active watchlist ticker, run `run_single_stock`. Persist `scan_runs` + `strike_gex_curve` + full `watchlist_card` row. Append `pcr_history` row | ~54 ticker calls per run |
| **Daily OHLC pull** | `UW_SCAN_OHLC_PULL_CRON` (default `30 17 * * 1-5` ET) | Fetch massive.io daily OHLC for every active watchlist ticker; upsert into `daily_ohlc`. Recompute `ret_1w`, `ret_30d` on the card | none |

All times in `UW_SCAN_RTH_TZ` (default `America/New_York`).

### 8.2 Ad-hoc rescan loop

Separate APScheduler job, 1-second tick. Polls `uw_scan.jobs WHERE status='queued'`, claims one (set `status='running'`, `started_at=now()`), runs `run_single_stock`, on success writes the report + recomputes the card + sets `status='done'`, `run_id`. On exception sets `status='failed'`, `error=repr(exc)`. Cooperative cancellation is out of scope for v1.

### 8.3 Config

Added to `src/uw_scan/config.py` `Settings`:

```python
spot_refresh_seconds: int = 300
full_scan_cron: str = "*/60 9-16 * * 1-5"
ohlc_pull_cron: str = "30 17 * * 1-5"
rth_tz: str = "America/New_York"
massive_io_api_key: SecretStr | None = None
massive_io_base_url: str = "https://api.massive.io"   # placeholder — confirmed in S3 spike, see §14
```

`.env.example` updated. The repo's existing `Settings.from_env()` pattern is preserved.

### 8.4 Health reporting

`/api/health` exposes `scheduler_lag_seconds = max(0, now - last_full_scan_finished_at)`. If `last_full_scan_finished_at` is null or older than 2× the full-scan interval, the response is `{ ok: false, ... }` and the watchlist page surfaces a warning banner.

## 9. Pipeline extensions

The S1 pipeline (`src/uw_scan/pipeline.py:run_single_stock`) and `SingleStockReport` need additive changes:

1. **Persist `strike_gex_curve` JSONB.** Already aggregated during S1 (the pipeline computes `total_call_gex` / `total_put_gex` / `net_gex` from per-strike data); we just keep the per-strike list and persist it on `scan_runs`. Required for `gex_flip_*`, `max_gex_strike`, `gex_expiring_*`, and the detail page's GEX chart.

2. **Fetch per-ticker bulk-screener row.** Call `/api/screener/stocks?ticker=...` (same endpoint S2 uses) during S1. Add fields to a new `MarketAggregates` sub-model on `SingleStockReport`:
   - `call_oi_total`, `put_oi_total`
   - `call_volume_total`, `put_volume_total`
   - `pcr_oi`, `pcr_vol`
   - `iv30d` (optional — already have `iv` and `iv_rank`)

3. **Verify `volatility.skew_25d` DTE.** Read the current pipeline; if it's not picking the 30-DTE expiry, normalise to 30 DTE (linear interpolation between surrounding expiries' 25Δ RR).

4. **`pcr_history` writer.** At the end of each successful `run_single_stock`, `INSERT ... ON CONFLICT (ticker, snapshot_date) DO UPDATE` a row with today's `pcr_oi` / `pcr_vol`.

5. **Massive.io provider.** New module `src/uw_scan/sources/ohlc.py`:
   ```python
   class OhlcProvider(Protocol):
       def fetch_daily(self, ticker: str, lookback_days: int) -> list[OhlcRow]: ...
       def fetch_intraday_quote(self, ticker: str) -> IntradayQuote: ...

   class MassiveIoOhlcProvider:  # concrete impl
       ...
   ```
   The provider is injected into the scheduler jobs. Tests use a recorded-fixture impl.

These changes are all **additive to `SingleStockReport`**. Old `scan_runs` rows remain valid; new fields default null. Pipeline contracts in the archived spec are preserved.

## 10. Frontend tab rendering (detail page)

The 6 tabs all consume the same `SingleStockReport` payload (fetched once at the layout level). Each tab is a thin renderer; no additional API calls per tab.

| Tab | Renders | New data needed |
|---|---|---|
| `market-structure` | `report.market_structure` + `strike_gex_curve` chart + `max_pain_rows` table | strike_gex_curve (new) |
| `volatility` | `report.volatility` + a term-structure line chart | none |
| `flow` | `report.flow` + `top_alerts` table | none |
| `vrp` | `report.vrp` | none |
| `trade-plan` | `report.setup` + `report.trade_plan` | none |
| `tables` | `oi_change_top`, dark-pool snapshot, `short_data` | none |

## 11. Testing approach

- **Unit (Python):** card-derivation pure functions (`compute_aggression_pct`, `find_gex_flip_strike`, `compute_returns`, `pcr_delta_30d`). Pure arithmetic, no fixtures.
- **Integration (Python, local Postgres):** scheduler jobs end-to-end with recorded UW + recorded massive.io fixtures → assert `watchlist_card` rows match expected snapshots. Migrations run against real `option_wizard.uw_scan`. **No fake cursors.**
- **API contract (Python, httpx + ASGI test client):** every FastAPI endpoint with seeded DB state, asserting response shape matches Pydantic models. OpenAPI schema is generated and snapshotted in CI to detect breaking changes.
- **Frontend unit (Vitest):** formatters, freshness bucketing, badge colour mapping, sparkline path generation.
- **Frontend integration (Vitest + Testing Library):** card renders all blocks with mock payload; filter chips drive URL state; rescan polling state machine.
- **End-to-end (Playwright):** one golden-path test — boot FastAPI with seeded DB + Next dev → load `/watchlist` → click TSLA → assert tabs work → click Rescan → assert polling and refresh.

The archived spec's guardrails (real Postgres for integration; no fake cursors; live data via the real UW client; explicit `Decimal` for prices) apply unchanged.

## 12. Cleanup actions (executed in S0)

1. `git mv docs/superpowers/specs/2026-05-11-uw-scan-design.md docs/superpowers/archive/specs/`
2. `git mv docs/superpowers/plans/2026-05-11-uw-scan-rebuild-plan.md docs/superpowers/archive/plans/`
3. `git mv docs/superpowers/plans/2026-05-12-uw-scan-s1.md docs/superpowers/archive/plans/`
4. `git mv docs/superpowers/plans/2026-05-12-uw-scan-s2.md docs/superpowers/archive/plans/`
5. `git rm -r app/`
6. `git rm s1-card-full.png s1-trade-plan-tab.png s2-full-scan.png`
7. Remove `streamlit` and any Streamlit-only deps from `pyproject.toml`
8. Add new sub-packages: `src/uw_scan/api/__init__.py`, `src/uw_scan/worker/__init__.py`, `src/uw_scan/sources/__init__.py`
9. Scaffold `web/` Next.js project (mirrors `xenon/web/`'s structure)
10. Add `scripts/dev.sh` that runs Next + uvicorn + scheduler concurrently

## 13. Slice plan

12 slices. S0–S6 are backend-only. S7–S12 are frontend.

| # | Slice | Deliverable | Depends on |
|---|---|---|---|
| **S0** | Repo cleanup + new package skeleton | §12 cleanup actions; empty Next.js scaffold under `web/`; `scripts/dev.sh`; CI updated to lint/test both Python and TS | — |
| **S1** | DB migrations + watchlist seed | All §4 tables + the `scan_runs.strike_gex_curve` column add. Seed `watchlist` from `data/watchlist_seed.json` (54 tickers). Integration test verifies migration roundtrip | S0 |
| **S2** | Pipeline extensions | (1) persist `strike_gex_curve`, (2) fetch per-ticker bulk-screener row + new `MarketAggregates` model, (3) verify/normalise `skew_25d` to 30 DTE, (4) `pcr_history` writer | S1 |
| **S3** | Massive.io provider + sources module | `OhlcProvider` interface + `MassiveIoOhlcProvider` + fixture-backed test provider. **Includes S0-style spike against the live API to confirm endpoints, auth, response shape.** | S0 |
| **S4** | Card-row derivation | `compute_watchlist_card_row()` pure function + full unit coverage; helper module `src/uw_scan/cards/` | S2, S3 |
| **S5** | FastAPI server | All endpoints in §5; Pydantic response models; contract tests; OpenAPI snapshot in CI | S4 |
| **S6** | Worker / scheduler | APScheduler with three configurable jobs + ad-hoc rescan loop; `/api/health` lag reporting; structured logging | S5 |
| **S7** | Frontend foundation | Next.js + Tailwind + fonts; copy xenon `globals.css` tokens; root layout; `lib/api.ts`; `lib/types.ts` generated from FastAPI OpenAPI | S5 |
| **S8** | Watchlist landing | `/watchlist` server component; `CardGrid`; sector grouping; filter chips via URL; `TickerCard` skeleton (frame only, no inner blocks) | S7 |
| **S9** | TickerCard sub-components | `CardHeader`, `SetupBadge`, `SparklineRow`, `AggressionGauge`, `GammaBlock`, `SkewBlock`, `PositioningBlock`. SVG + Tailwind only, no data fetching | S8 |
| **S10** | Detail page foundation | `/stock/[ticker]/layout.tsx` (header strip + tab nav); redirect to default tab | S7 |
| **S11** | Detail page tabs | 6 tab pages; `MetricGrid` / `DataTable` / `GexChart` panel primitives | S10 |
| **S12** | Mutations + admin + E2E | Add/Remove/Edit dialogs; `RescanButton` client island; `/admin` status page; Playwright golden-path E2E | S6, S9, S11 |

Critical-path: S0 → S1 → S2 → S4 → S5 → S6 (then frontend tier from S7 onwards). S3 is independent of S2 and can run in parallel. S8/S9 depend on S5 having shipped (need the API + types).

## 14. Open questions

1. **massive.io API surface.** I have not verified the actual endpoint shape, auth model, rate limits, or whether the intraday quote is 15-minute delayed as the user described. S3 starts with a discovery spike that resolves this. If massive.io turns out to be unsuitable, the `OhlcProvider` interface lets us swap to polygon/eodhd/Yahoo without touching the rest of the system. (The project CLAUDE.md forbids Yahoo as a *primary* data source — fallback is acceptable.)
2. **Current `volatility.skew_25d` DTE.** Need to read `pipeline.py` and `sources/` to determine which expiry's 25Δ RR is currently persisted to that field. Resolved in S0 or early S2.
3. **Migration runner.** Migration files follow the existing `00N_<topic>.sql` convention in `src/uw_scan/storage/migrations/`. S1 must verify how those files are actually applied today (a Python runner in `Repository`? a shell script? manual `psql`?) and reuse the same mechanism.
4. **Watchlist sort persistence.** The `sort_rank` column allows drag-to-reorder, but the v1 UI may not implement drag-and-drop. Default sort: pinned first, then alphabetical within sector. Confirm before S8.

## 15. Acceptance criteria

Implementation is complete when:

1. `scripts/dev.sh` boots Next, FastAPI, and the scheduler with no errors. `/watchlist` loads, populated, in <500 ms initial paint.
2. All 54 seeded tickers render as cards with the full 7-block layout (header, setup badge, sparkline + returns, aggression gauge, gamma block, skew block, positioning block). Missing data renders as "—", never as `null` or fabricated zero.
3. Clicking a card navigates to `/stock/{ticker}/market-structure`. All 6 tabs render the existing `SingleStockReport` content without errors.
4. `POST /api/watchlist` adds a ticker; it appears in the next scheduler tick's card grid. `DELETE` soft-deletes. `PATCH` edits notes/sector/pinned/sort_rank.
5. Rescan button on a card triggers a job, the spinner reflects progress, the card refreshes when done.
6. `/api/health` reports the scheduler lag accurately; manually killing the worker for >2× the full-scan interval surfaces a warning banner on `/watchlist`.
7. All tests pass (Python unit + integration; TS unit + integration; one Playwright E2E).
8. Streamlit code is gone from the repo. `app/`, the Streamlit dep, and the three Streamlit screenshots no longer exist on `main`.

---

*End of design spec.*
