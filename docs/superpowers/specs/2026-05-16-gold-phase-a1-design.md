# Gold Endpoint Phase A1 — Research Cockpit with Audit Scaffold (Design Spec)

**Status:** Draft for review
**Author:** brainstorming session, 2026-05-16
**Scope:** Phase A1 of the Option A-prime plan from [docs/research/gold-sdf-framework/10-open-research-questions.md Q13](../../research/gold-sdf-framework/10-open-research-questions.md)
**Foundation:** [docs/research/gold-sdf-framework/](../../research/gold-sdf-framework/) (entire research directory)
**Companion notes:**
- Codex adversarial review: [docs/reviews/2026-05-16-gold-research-codex-review.md](../../reviews/2026-05-16-gold-research-codex-review.md)
- Standing rule honoured: every persistable artifact this spec produces is written back to Postgres (`schema uw_scan`) — no in-memory-only results.
- No naked shorts, no Yahoo fallback, uv-only Python, IB/UW/FMP/massive data priority — per top-level CLAUDE.md.

---

## 1. Goals

Phase A1 ships a **research cockpit for Gold** with an **audit-ready data layer from day one**. The cockpit shows posture (not recommendations) across three signal-family lenses; the data layer persists raw inputs and transformed factors with point-in-time discipline so that Phase A3 can build a backtest harness without retrofit.

Six concrete goals:

1. **Ingest every required data series** for the three lenses, persisted to Postgres with explicit as-of timestamps and release-date metadata. Sources: FRED, GPR (Caldara-Iacoviello), SPDR ETF holdings, BlackRock IAU holdings, CME COMEX vault, LBMA vault, WGC central-bank reserves, CFTC COT, UW options snapshots (gold complex), FX (DEXCHUS/DEXINUS/DEXJPUS, plus TRY via BIS/TCMB).
2. **Compute the correlation gauge** (rolling Gold ↔ DFII10 across 60d/126d/252d/504d windows, both levels and returns specs) and persist daily.
3. **Compute and persist daily posture rows** — per-lens narrative state derived from current inputs, with full traceability back to the raw inputs that produced the posture.
4. **Read-only API surface** at `/api/gold/*` exposing latest posture, lens inputs, regime gauge, and historical replay.
5. **Deterministic replay scaffold** — `GET /api/gold/replay?as_of=YYYY-MM-DD` returns the exact cockpit state for any historical date, using only data available at that decision time.
6. **Cockpit page** at `web/app/gold/page.tsx` — product name **GOLD COMPASS** — rendering a five-tier layout (banner KPIs · Lens 1 structural · Lens 2 cyclical · Lens 3 valuation · decomposition + correlation history) with explicit gauge banner, posture statements, and "framework suspended" copy when applicable. Visual reference: `gold-monitor-delta.vercel.app` (factor-grid trader dashboard), adapted to our Argon dark / mono-uppercase token vocabulary and stripped of any surface that would require a model in A1 (predicted return, signal long/short, equity curve, position heat).

**Implicit goal — the data ratchet.** From day one, every day the cockpit runs accumulates backtest-ready data. This is the load-bearing feature that distinguishes Option A-prime from Option A.

---

## 2. Non-goals

Phase A1 explicitly does NOT include:

- **Any trained ML model.** No linear regression, no XGBoost, no state-space, no HMM. Posture is rule-based and deterministic.
- **Numerical position recommendations.** v1 emits posture / risk / scenario language only. No A position size, no B position size, no Kelly composition. Per [docs/research/gold-sdf-framework/04-three-layer-architecture.md](../../research/gold-sdf-framework/04-three-layer-architecture.md) and the Codex flag on premature recommendation language.
- **Walk-forward backtest harness.** That is Phase A3. Phase A1's "replay" is *deterministic playback of historical posture*, not a tradable backtest.
- **Internal replication of the post-2022 correlation collapse.** Computing the gauge values is in A1; running the formal structural-break tests against multiple windows / specs / break dates is **Phase A2**.
- **Article-zone threshold calibration.** A1 ships article defaults (CPI 2/4%, T5YIFR 2.5/2.7/2.8%) clearly labeled "heuristic, not validated." Empirical calibration is Phase A2.
- **Target-definition lock-in.** A1 uses GLD ETF close as the primary gold reference. LBMA fix and GC=F as side panels. Choosing the canonical target for eventual modeling is Phase A2.
- **Benchmark comparisons.** Defined in Phase A2.
- **Validation basket** (deflated Sharpe, PBO, regime-conditional Sharpe). No model → no validation. Phase A3.
- **Multi-task pooling, partial pooling, or any cross-asset training.** Phase A3+.
- **Shanghai Gold Exchange (SGE) physical inventory ingest.** Deferred to v2 because of Chinese-language scraping cost; partially covered by per-country CB reserves + XAU/CNY.
- **GOFO / gold lease rate.** GOFO discontinued by LBMA in January 2015. Use COMEX/LBMA inventory and SGE premium as proxies (proxies are in A1 only via the COMEX and LBMA series; lease-rate-specific construction is v2 research).
- **Light theme, mobile-specific layout, or real-time streaming.** Dark only, desktop-first, page-load fetch — consistent with existing `web/app/` conventions.

---

## 3. Architecture overview

Phase A1 slots into the existing repo skeleton without inventing new patterns. Each new component mirrors an existing analogue.

```
                    ┌─────────────────────────────────────────────┐
                    │  External data sources (free / already paid) │
                    │   FRED, GPR, SPDR, iShares, CME, LBMA, WGC,  │
                    │   CFTC, UW (gold complex), BIS/TCMB FX        │
                    └────────────────────┬────────────────────────┘
                                         │
                ┌────────────────────────┴────────────────────────┐
                │  Sources (Python clients, telemetry-wrapped)    │
                │   src/uw_scan/sources/fred.py          [NEW]    │
                │   src/uw_scan/sources/gpr.py           [NEW]    │
                │   src/uw_scan/sources/etf_holdings.py  [NEW]    │
                │   src/uw_scan/sources/comex.py         [NEW]    │
                │   src/uw_scan/sources/lbma.py          [NEW]    │
                │   src/uw_scan/sources/wgc_cb.py        [NEW]    │
                │   src/uw_scan/sources/cftc_cot.py      [NEW]    │
                │   src/uw_scan/sources/uw.py            [REUSE]  │
                │   src/uw_scan/sources/ohlc.py          [REUSE]  │
                │   (each emits ExternalApiRequestEvent telemetry)│
                └────────────────────┬────────────────────────────┘
                                     │
                ┌────────────────────┴────────────────────────────┐
                │  Storage / repository                            │
                │   src/uw_scan/storage/repository.py    [EXTEND] │
                │   one method per query, per repo convention     │
                │   Schema uw_scan, ~7 new tables (see §4)        │
                │   ALL writes carry observed_at (UTC) and        │
                │   as_of_releases (release-date metadata).       │
                └────────────────────┬────────────────────────────┘
                                     │
                ┌────────────────────┴────────────────────────────┐
                │  Reports / cards (derivations)                  │
                │   src/uw_scan/reports/gold_posture.py  [NEW]    │
                │   src/uw_scan/cards/regime_gauge.py    [NEW]    │
                │   src/uw_scan/cards/structural_flow.py [NEW]    │
                │   src/uw_scan/cards/cyclical_zones.py  [NEW]    │
                │   src/uw_scan/cards/valuation.py       [NEW]    │
                │   (pure functions over repo state, no I/O)      │
                └────────────────────┬────────────────────────────┘
                                     │
                ┌────────────────────┴────────────────────────────┐
                │  API surface                                    │
                │   src/uw_scan/api/routers/gold.py      [NEW]    │
                │     GET /api/gold/state                         │
                │     GET /api/gold/lenses/{lens_id}              │
                │     GET /api/gold/gauge                         │
                │     GET /api/gold/replay?as_of=YYYY-MM-DD       │
                │     GET /api/gold/inputs/{series}               │
                └────────────────────┬────────────────────────────┘
                                     │
                ┌────────────────────┴────────────────────────────┐
                │  Scheduled worker                               │
                │   src/uw_scan/worker/scheduler.py      [EXTEND] │
                │   New jobs:                                     │
                │     gold_fred_ingest          (daily, 17:00 ET) │
                │     gold_etf_holdings_ingest  (daily, 18:30 ET) │
                │     gold_comex_vault_ingest   (daily, 17:30 ET) │
                │     gold_lbma_vault_ingest    (monthly, 6th day)│
                │     gold_wgc_cb_ingest        (monthly, 8th day)│
                │     gold_cftc_cot_ingest      (weekly, Fri 16:00)│
                │     gold_gpr_ingest           (daily, 20:00 ET) │
                │     gold_uw_options_snapshot  (daily, 16:30 ET) │
                │     gold_posture_compute      (daily, 21:00 ET, │
                │                                after all ingest)│
                └────────────────────┬────────────────────────────┘
                                     │
                ┌────────────────────┴────────────────────────────┐
                │  Web cockpit — "GOLD COMPASS"                   │
                │   web/app/gold/page.tsx                [NEW]    │
                │   web/components/gold/*                [NEW]    │
                │     GoldCompassLayout (5-tier shell)            │
                │     kpi/ {Spot,CorrGauge,Regime,Lenses,Data}    │
                │     lens1/ structural cards + lead chart        │
                │     lens2/ cyclical cards + two-force narrative │
                │     lens3/ valuation cards (never sizing input) │
                │     decomposition/ + correlation/ history       │
                │     DataAuditFooter · ReplayDatePicker          │
                │   web/lib/types.ts                     [EXTEND] │
                │   (regenerated via openapi-typescript)          │
                └─────────────────────────────────────────────────┘
```

**Reuse note:** every "[NEW]" file follows the shape of an existing analogue. `sources/fred.py` mirrors `sources/ohlc.py` (provider class, fetch methods, telemetry). `api/routers/gold.py` mirrors `api/routers/stock.py`. The worker jobs follow the existing scheduler.py patterns.

---

## 4. Data model

All tables live in schema `uw_scan`. Migrations are idempotent (`IF NOT EXISTS`, `ON CONFLICT DO NOTHING`), per the repo's standing rule. Migration files: `migrations/202605160001_gold_macro_series.sql` through `…0008_gold_posture_rows.sql`.

### 4.1 `macro_series_daily`

```sql
CREATE TABLE IF NOT EXISTS uw_scan.macro_series_daily (
  series_id     TEXT        NOT NULL,    -- FRED ID or our convention: 'DFII10', 'T5YIFR', 'GPRD', 'XAUCNY_PREMIUM', etc.
  obs_date      DATE        NOT NULL,    -- observation date (the day the value pertains to)
  value         NUMERIC     NOT NULL,
  as_of         TIMESTAMPTZ NOT NULL,    -- when we ingested this row (UTC); for vintage tracking
  release_date  DATE        NULL,        -- publication date if different from obs_date (for CPI vintages, etc.)
  source        TEXT        NOT NULL,    -- 'FRED', 'GPR', 'COMPUTED'
  source_url    TEXT        NULL,
  PRIMARY KEY (series_id, obs_date, as_of)
);
CREATE INDEX IF NOT EXISTS idx_macro_series_daily_lookup
  ON uw_scan.macro_series_daily (series_id, obs_date DESC);
```

The `(series_id, obs_date, as_of)` PK lets us store multiple vintages of the same observation — critical for CPI which gets revised, and useful for any FRED series we re-pull. The "current" value for `obs_date = X` is `ORDER BY as_of DESC LIMIT 1`.

### 4.2 `macro_series_monthly`

Same shape as `macro_series_daily` but indexed monthly. Used for CPIAUCSL and any monthly inputs that aren't already in `macro_series_daily`. Could be one combined table; keeping separate for query clarity.

### 4.3 `etf_holdings_daily`

```sql
CREATE TABLE IF NOT EXISTS uw_scan.etf_holdings_daily (
  ticker        TEXT        NOT NULL,    -- 'GLD', 'IAU', 'GLDM', 'PHYS'
  obs_date      DATE        NOT NULL,
  holdings_oz   NUMERIC     NULL,        -- tonnes × 32150.7 if tonnes-native; oz canonical
  shares_out    NUMERIC     NULL,
  nav_per_share NUMERIC     NULL,
  premium_pct   NUMERIC     NULL,        -- PHYS-specific
  as_of         TIMESTAMPTZ NOT NULL,
  source        TEXT        NOT NULL,    -- 'SPDR', 'iShares', 'Sprott'
  PRIMARY KEY (ticker, obs_date, as_of)
);
```

### 4.4 `exchange_inventory_daily`

```sql
CREATE TABLE IF NOT EXISTS uw_scan.exchange_inventory_daily (
  exchange      TEXT        NOT NULL,    -- 'COMEX', 'LBMA'
  obs_date      DATE        NOT NULL,
  registered_oz NUMERIC     NULL,        -- COMEX
  eligible_oz   NUMERIC     NULL,        -- COMEX
  vault_oz      NUMERIC     NULL,        -- LBMA total
  as_of         TIMESTAMPTZ NOT NULL,
  source_url    TEXT        NULL,
  PRIMARY KEY (exchange, obs_date, as_of)
);
```

LBMA is monthly; row keyed by month-end date. COMEX is daily.

### 4.5 `cb_gold_reserves_monthly`

```sql
CREATE TABLE IF NOT EXISTS uw_scan.cb_gold_reserves_monthly (
  country_iso3  TEXT        NOT NULL,    -- 'CHN', 'IND', 'RUS', 'TUR', 'POL', etc.
  obs_month     DATE        NOT NULL,    -- first of month
  reserves_t    NUMERIC     NULL,        -- tonnes; NULL if country didn't report (e.g., Russia post-2022)
  bucket        TEXT        NOT NULL,    -- 'strategic_accumulator', 'tactical_defender', 'reserve_diversifier'
  is_reported   BOOLEAN     NOT NULL DEFAULT TRUE,
  is_estimated  BOOLEAN     NOT NULL DEFAULT FALSE,  -- TRUE for industry-estimated rows
  as_of         TIMESTAMPTZ NOT NULL,
  release_date  DATE        NULL,
  source        TEXT        NOT NULL,    -- 'WGC', 'IMF_IFS', 'INDUSTRY'
  PRIMARY KEY (country_iso3, obs_month, as_of)
);
```

Bucket assignment is config-driven in `src/uw_scan/cards/structural_flow.py` so we can adjust without migration. Default classification per [docs/research/gold-sdf-framework/05-structural-flow-factors.md](../../research/gold-sdf-framework/05-structural-flow-factors.md).

### 4.6 `cot_gold_weekly`

```sql
CREATE TABLE IF NOT EXISTS uw_scan.cot_gold_weekly (
  obs_date          DATE        NOT NULL,  -- Tuesday position date
  release_date      DATE        NOT NULL,  -- Friday publication date
  mm_long           NUMERIC     NULL,      -- managed-money longs
  mm_short          NUMERIC     NULL,
  mm_net            NUMERIC     NULL,
  comm_long         NUMERIC     NULL,      -- commercials
  comm_short        NUMERIC     NULL,
  comm_net          NUMERIC     NULL,
  open_interest     NUMERIC     NULL,
  as_of             TIMESTAMPTZ NOT NULL,
  source_url        TEXT        NULL,
  PRIMARY KEY (obs_date, as_of)
);
```

`release_date` is critical: any backtest must lag COT inputs by 3 trading days, never to observation date.

### 4.7 `uw_gold_options_daily`

Persistence-only in A1 — not consumed by any A1 computation. Backtest history accumulates from day one so Phase A3 has data to work with.

```sql
CREATE TABLE IF NOT EXISTS uw_scan.uw_gold_options_daily (
  ticker            TEXT        NOT NULL,  -- 'GLD', 'GDX', 'IAU'
  obs_date          DATE        NOT NULL,
  atm_iv_30d        NUMERIC     NULL,
  atm_iv_60d        NUMERIC     NULL,
  put_25d_iv_30d    NUMERIC     NULL,
  call_25d_iv_30d   NUMERIC     NULL,
  skew_25d_30d      NUMERIC     NULL,      -- put_25d_iv - call_25d_iv
  put_call_oi_ratio NUMERIC     NULL,
  dealer_gamma_est  NUMERIC     NULL,      -- raw or normalized; convention TBD
  as_of             TIMESTAMPTZ NOT NULL,
  PRIMARY KEY (ticker, obs_date, as_of)
);
```

Sourced via UW endpoints already integrated for other tickers; same `UwClient` patterns from `sources/uw.py`.

### 4.8 `gold_posture_daily`

The persisted daily posture across the three lenses — the load-bearing replay/audit table.

```sql
CREATE TABLE IF NOT EXISTS uw_scan.gold_posture_daily (
  obs_date                 DATE        NOT NULL,
  computed_at              TIMESTAMPTZ NOT NULL,    -- when this posture was computed (UTC)

  -- correlation gauge
  gauge_corr_60d           NUMERIC     NULL,
  gauge_corr_126d          NUMERIC     NULL,
  gauge_corr_252d          NUMERIC     NULL,
  gauge_corr_504d          NUMERIC     NULL,
  gauge_corr_252d_returns  NUMERIC     NULL,        -- returns spec, for sanity-check
  gauge_state              TEXT        NOT NULL,    -- 'operative', 'partial', 'suspended'

  -- structural posture (Lens 1)
  structural_state_label   TEXT        NULL,        -- e.g. 'structural-bid-intact'
  cb_strategic_12m_sum_t   NUMERIC     NULL,        -- tonnes
  cb_tactical_12m_sum_t    NUMERIC     NULL,
  cb_diversifier_12m_sum_t NUMERIC     NULL,
  gld_holdings_t           NUMERIC     NULL,
  gld_30d_net_flow_t       NUMERIC     NULL,
  comex_registered_oz      NUMERIC     NULL,
  comex_20d_roc_pct        NUMERIC     NULL,
  cot_mm_net_pct           NUMERIC     NULL,        -- percentile of managed-money net within 5y window

  -- cyclical posture (Lens 2)
  cyclical_zone_label      TEXT        NULL,        -- 'real-rate-driven', 'moderate-trap', 'article-unanchored', 'transitional'
  cpi_yoy                  NUMERIC     NULL,
  t5yifr                   NUMERIC     NULL,
  dfii10                   NUMERIC     NULL,
  dfii10_60d_change_bps    NUMERIC     NULL,
  factors_jsonb            JSONB       NULL,        -- F1..F21 z-scores or percentiles for the panel

  -- valuation overlay (Lens 3)
  valuation_flag           TEXT        NULL,        -- 'Low', 'Moderate', 'High', 'Severe'
  real_price_percentile    NUMERIC     NULL,
  gold_m2_ratio_percentile NUMERIC     NULL,
  gold_spx_ratio_percentile NUMERIC    NULL,

  -- posture text (computed, ready for UI)
  structural_posture_text  TEXT        NULL,        -- 1-2 sentence narrative
  cyclical_posture_text    TEXT        NULL,
  valuation_posture_text   TEXT        NULL,

  -- provenance
  inputs_jsonb             JSONB       NOT NULL,    -- map of {series_id: (obs_date, as_of)} used to compute this row

  PRIMARY KEY (obs_date, computed_at)
);
CREATE INDEX IF NOT EXISTS idx_gold_posture_daily_latest
  ON uw_scan.gold_posture_daily (obs_date DESC, computed_at DESC);
```

The `inputs_jsonb` is the replay-scaffold backbone: it pins exactly which (series_id, observation, vintage) was used to compute each posture row. Replay queries reconstruct the same posture by querying the inputs at the same vintages.

---

## 5. Data sources and ingestion

Each source becomes a Python module in `src/uw_scan/sources/`. All modules expose a `Provider` class with telemetry-wrapped fetch methods, mirroring the existing `MassiveOhlcProvider` shape and emitting `ExternalApiRequestEvent` rows to the existing `provider_usage` table.

### 5.1 FRED (`sources/fred.py`)

Implements two endpoint paths:
- **CSV endpoint** (default, no auth): `https://fred.stlouisfed.org/graph/fredgraph.csv?id=<SERIES_ID>` — used by the daily worker for full-series refresh
- **JSON API** (config-gated): `https://api.stlouisfed.org/fred/series/observations?series_id=<X>&api_key=<KEY>` — reserved for cases where we need ALFRED vintage data (Phase A2 / A3, not A1)

Series ingested daily in A1:

```python
FRED_SERIES_DAILY = [
    "DFII10", "DGS10", "T10YIE", "T5YIFR",
    "DTWEXBGS", "BAMLH0A0HYM2", "VIXCLS", "GVZCLS",
    "DEXCHUS", "DEXINUS", "DEXJPUS",
    "CBBTCUSD",  # for future four-asset board, persist now
]
FRED_SERIES_MONTHLY = ["CPIAUCSL", "M2SL"]
```

Each row inserted with `source='FRED'`, `as_of=NOW()`, `release_date=NULL` for daily series (release timing is same-day for daily Treasury data) or estimated CPI release date for CPIAUCSL.

### 5.2 GPR (`sources/gpr.py`)

Fetches Caldara-Iacoviello daily GPR CSV from `matteoiacoviello.com/gpr.htm` (parses the file link, downloads, writes rows to `macro_series_daily` with `series_id='GPRD'`, `source='GPR'`).

### 5.3 ETF holdings (`sources/etf_holdings.py`)

Four small fetchers in one module:
- **GLD**: SPDR daily CSV — already published historical data + daily appendable
- **IAU**: BlackRock investor-relations page; either CSV download or HTML parse
- **GLDM**: SPDR daily CSV (sister fund, same site)
- **PHYS**: Sprott investor relations; daily NAV + premium published

All write to `etf_holdings_daily` with `source` set appropriately.

### 5.4 COMEX vault (`sources/comex.py`)

Daily CME gold-stocks report scrape. URL: `https://www.cmegroup.com/markets/metals/precious/gold-stocks.html`. Parses registered, eligible, and total ounces. Writes to `exchange_inventory_daily` with `exchange='COMEX'`.

### 5.5 LBMA vault (`sources/lbma.py`)

Monthly CSV from LBMA "Vault Holdings Data" page. Writes to `exchange_inventory_daily` with `exchange='LBMA'`.

### 5.6 WGC central-bank reserves (`sources/wgc_cb.py`)

Monthly CSV from `gold.org/goldhub/data/monthly-central-bank-statistics`. Maps country to ISO3 (config-driven), assigns bucket (config-driven). Writes to `cb_gold_reserves_monthly`. Russia rows handled per the `is_reported=FALSE` flag when WGC explicitly marks them as estimated; otherwise data goes in as-published.

### 5.7 CFTC COT (`sources/cftc_cot.py`)

Weekly CSV from CFTC. Disaggregated report preferred for clean managed-money / commercial breakdown. Critical: persist `obs_date` (Tuesday positions) AND `release_date` (Friday publication) as separate columns. Any analytical consumer must filter on `release_date <= decision_date`.

### 5.8 UW gold options snapshot (`sources/uw.py` extension)

Reuses the existing `UwClient` infrastructure. New methods: `fetch_options_chain('GLD', date)`, similar for GDX/IAU. Computes ATM IV at 30d/60d, 25-delta put/call IVs, skew, dealer-gamma proxy from chain data. Writes to `uw_gold_options_daily`.

**No A1 consumption — persistence only.** This factor class is part of the data ratchet: even though no A1 cockpit panel uses these columns, the data accumulates daily so that Phase A3 model promotion has history to work with.

### 5.9 FX local-currency gold (computed, no new source)

XAU/CNY, XAU/INR, XAU/JPY, XAU/TRY computed in `cards/structural_flow.py` from existing inputs (USD gold price × FX cross). TRY requires a small BIS-or-TCMB fetcher; defer if it slows the v1 spec acceptance, use placeholder `NULL` until added (A2 task).

### 5.10 Scheduler integration (`worker/scheduler.py`)

Eight new APScheduler jobs added:

| Job ID | Schedule | Purpose |
|---|---|---|
| `gold_fred_ingest` | daily, 17:00 ET (after FRED's typical 4 PM update) | refresh FRED_SERIES_DAILY + monthly when release dates match |
| `gold_gpr_ingest` | daily, 20:00 ET | refresh GPRD |
| `gold_etf_holdings_ingest` | daily, 18:30 ET | GLD/IAU/GLDM/PHYS |
| `gold_comex_vault_ingest` | daily, 17:30 ET | COMEX scrape |
| `gold_lbma_vault_ingest` | monthly, 6th business day, 12:00 ET | LBMA monthly CSV |
| `gold_wgc_cb_ingest` | monthly, 8th business day, 12:00 ET | WGC CSV |
| `gold_cftc_cot_ingest` | weekly, Friday 16:00 ET | COT release |
| `gold_uw_options_snapshot` | daily, 16:30 ET (after market close) | UW chain snapshots |
| `gold_posture_compute` | daily, 21:00 ET (after all ingest) | compute and persist `gold_posture_daily` row |

All jobs use existing `ExternalApiRequestEvent` telemetry. All jobs are idempotent under re-run (PK includes `as_of`, so re-running just adds a new vintage row).

---

## 6. API surface

All endpoints under `src/uw_scan/api/routers/gold.py`. Read-only — mutations only via `/jobs`, per top-level CLAUDE.md.

### 6.1 `GET /api/gold/state`

Returns the current (latest computed) `gold_posture_daily` row, decoded into a typed response:

```python
class GoldStateResponse(BaseModel):
    obs_date: date
    computed_at: datetime
    gauge: GoldGaugeState
    structural: StructuralPosture
    cyclical: CyclicalPosture
    valuation: ValuationPosture
    inputs_used: dict[str, InputProvenance]  # series_id -> (obs_date, as_of)
```

### 6.2 `GET /api/gold/lenses/{lens_id}`

Detail view for one lens. `lens_id` in `{"structural", "cyclical", "valuation"}`. Returns the lens-specific signals as a richer payload — e.g., for `structural` returns CB bucket sums, per-country deltas, ETF holdings time series last 90 days, COMEX inventory time series last 60 days, COT panel.

### 6.3 `GET /api/gold/gauge`

Just the correlation gauge: current values across 60d/126d/252d/504d windows, current state, and a time series of the 252d window for the last 5 years (for the headline regime chart).

### 6.4 `GET /api/gold/replay?as_of=YYYY-MM-DD`

The replay/audit endpoint. Returns the `gold_posture_daily` row for the requested date, AS-COMPUTED-ON-THE-DAY (the row's `computed_at` should be near `obs_date + 1 day`). Use case: "what did the cockpit say on 2026-04-15? Are we able to reconstruct the same posture deterministically?"

Implementation: select the most-recent `computed_at` for the given `obs_date` (so we get the v1 of the posture, not any later recomputation).

### 6.5 `GET /api/gold/inputs/{series_id}`

Per-series time series. Supports `?from=YYYY-MM-DD&to=YYYY-MM-DD`. Used by the cockpit's per-series detail tooltips and the audit views. Reads from `macro_series_daily` / `etf_holdings_daily` / etc. depending on series.

### 6.6 OpenAPI type flow

The new types under `src/uw_scan/models.py` follow the existing `openapi-typescript` flow: types regenerated into `web/lib/types.ts` via `cd web && npm run gen:types`. No new pipeline.

---

## 7. Computation logic (cards/reports)

Pure functions, no I/O. All consume rows from the repository, produce derived structures.

### 7.1 `cards/regime_gauge.py`

```python
def compute_correlation_gauge(
    gold_series: list[tuple[date, Decimal]],  # GLD daily closes
    dfii10_series: list[tuple[date, Decimal]],
    as_of: date,
) -> CorrelationGauge:
    """Compute Gold ↔ DFII10 rolling correlations at 60d / 126d / 252d / 504d windows,
    both price-level and log-return specifications, all anchored at `as_of`."""
```

Returns a `CorrelationGauge` with 8 correlation values (4 windows × 2 specs) plus the derived state label (`'operative' | 'partial' | 'suspended'`) using default thresholds. Thresholds configurable per Phase A2 (Q1 / Q20 in [docs/research/gold-sdf-framework/10-open-research-questions.md](../../research/gold-sdf-framework/10-open-research-questions.md)).

### 7.2 `cards/structural_flow.py`

```python
def compute_structural_posture(
    cb_rows: list[CbReserveRow],
    etf_rows: list[EtfHoldingsRow],
    inventory_rows: list[InventoryRow],
    cot_rows: list[CotRow],
    fx_rows: list[FxRow],
    gold_series: list[GoldQuote],
    as_of: date,
) -> StructuralPosture:
    """Compute Lens 1 posture: bucket sums, GLD flow z-score, COMEX 20d ROC,
    XAU/local-currency premia, COT percentiles. Returns rich struct with
    1-sentence narrative."""
```

The narrative is generated by a simple deterministic template — no LLM in A1. Template chooses among a small set of pre-written phrases based on signal states.

### 7.3 `cards/cyclical_zones.py`

```python
def compute_cyclical_posture(
    cpi_yoy: Decimal,
    t5yifr: Decimal,
    dfii10: Decimal,
    dfii10_60d_change_bps: Decimal,
    factors: dict[str, Decimal],  # F1..F21 z-scores
    gauge_state: str,
) -> CyclicalPosture:
    """Compute Lens 2 posture: article zone label (heuristic, explicitly tagged
    'article zone' not 'regime'), two-force direction, factor grid values.
    Narrative respects the gauge state — if suspended, returns informative-only
    framing, never recommendation language."""
```

### 7.4 `cards/valuation.py`

```python
def compute_valuation_overlay(
    gold_series: list[tuple[date, Decimal]],
    cpi_series: list[tuple[date, Decimal]],
    m2_series: list[tuple[date, Decimal]],
    spx_series: list[tuple[date, Decimal]],
    as_of: date,
) -> ValuationOverlay:
    """Compute real-price percentile, gold/M2 percentile, gold/SPX percentile.
    Returns flag in {'Low', 'Moderate', 'High', 'Severe'} with the
    'never a sizing input' framing baked into copy."""
```

### 7.5 `reports/gold_posture.py`

Top-level orchestrator. Reads inputs, calls each card, assembles a complete `gold_posture_daily` row including `inputs_jsonb` provenance. Single entry point used by the `gold_posture_compute` worker job.

---

## 8. GOLD COMPASS cockpit UI (web/app/gold)

Server-component shell with client islands for charts and interactivity, consistent with `web/app/stock/[ticker]/page.tsx` patterns.

**Product name:** GOLD COMPASS. Used as the page title, header chip, and footer wordmark.

**Visual inspiration:** `gold-monitor-delta.vercel.app` (factor-grid trader dashboard). Captured 2026-05-17 via Playwright MCP. Reference artifacts:
- Screenshot: [docs/research/gold-sdf-framework/_references/gold-monitor-reference-2026-05-17.png](../../research/gold-sdf-framework/_references/gold-monitor-reference-2026-05-17.png)
- Accessibility-tree snapshot: [docs/research/gold-sdf-framework/_references/gold-monitor-snapshot-2026-05-17.md](../../research/gold-sdf-framework/_references/gold-monitor-snapshot-2026-05-17.md) We borrow its information architecture — banner KPIs, factor card grid, regime panel, decomposition tabs — but render it in the existing Argon dark / mono-uppercase token vocabulary (`--bg-panel`, `--positive`, `--negative`, `--warning`, `--accent-bg`, mono 10/22/11px) used by `components/stock/panels/VolMetricsCard.tsx` and `components/stock/panels/AnalyticalSeriesPanel.tsx`. No new design tokens introduced.

**Surfaces removed from the reference** (because Phase A1 cannot honestly produce them):

| Reference surface | Why removed | GOLD COMPASS A1 substitute |
|---|---|---|
| `今日信号: 做多 / 做空` (today's long/short signal) | No model in A1 | Per-lens posture chip (`FAVORABLE / NEUTRAL / STRETCHED / SUSPENDED`) |
| `预测收益 +0.72%` (predicted return) | No model in A1 | `STRUCTURAL FLOW SCORE` tile (raw lens output, untransformed) |
| `仓位热度 1.20%` (position heat) | No sizing in A1 | `CORRELATION GAUGE` tile (gold ↔ DFII10 252d) |
| `当前回撤 -1.89%` (current drawdown) | No backtest in A1 | `REGIME BADGE` (R1/R2/R3 from cyclical zones) |
| `SHAP attribution waterfall` | No model in A1 | `LENS DECOMPOSITION` (which sub-factor of each lens drove its current state — bars over heuristic contributions, not model attributions) |
| `IC tracking` tab | No model → no IC in A1 | `CORRELATION HISTORY` (rolling correlations: gold ↔ DFII10 / DXY / GPR) |
| `净值曲线 / equity curve` tab | No backtest in A1 | `REPLAY` route — first-computed posture history per §9 |
| `回测账户` panel (Sharpe, MDD, win rate) | No backtest in A1 | `DATA FRESHNESS` panel (last-fetch timestamps + vintage age per source) |
| `XGBoost · 8因子` footer chip | No model in A1 | `LENS HEURISTICS · v1` footer chip |
| `A仓位 / B仓位` numeric weights | Premature sizing | `A POSTURE CONTEXT (long-horizon)` / `B POSTURE CONTEXT (event-hedge)` — narrative chips, not weights |
| Gold-amber brand color | Inconsistent with rest of app | Argon teal `--accent-bg`; amber `--warning` reserved for stretched-valuation and stale-data states only |

This is intentional: the reference uses MOCK labels on every value because it knows the numbers aren't real; we make the v1 cockpit honest by removing the surfaces that would need MOCK labels.

### 8.1 Page route

```
web/app/gold/
├── page.tsx                 # RSC shell, fetches /api/gold/state server-side
├── replay/[date]/page.tsx   # RSC shell for /api/gold/replay?as_of=...
└── loading.tsx
```

### 8.2 Layout

GOLD COMPASS uses a **five-tier vertical stack** on a 12-column grid at desktop, collapsing to a single column on narrow viewports. All tiles share the canonical `Tile` shape from `components/stock/panels/VolMetricsCard.tsx`: 10px mono uppercase label, 22px bold mono value, 11px mono sub. Section headers use the `AnalyticalSeriesPanel` titled-frame pattern.

```
┌─ TIER 1: HEADER + KPI STRIP ────────────────────────────────────────────────┐
│  GOLD COMPASS                       [R1·R2·R3]   [Replay: 2026-05-17 ▾]    │
│  Heuristic posture monitor · v1                                              │
│                                                                              │
│  ┌─XAU/USD─────────┐ ┌─CORR GAUGE─┐ ┌─REGIME──┐ ┌─LENSES OVERALL─┐ ┌─DATA─┐│
│  │ GOLD SPOT        │ │ GOLD↔DFII10│ │ ARTICLE │ │ S· FAVORABLE   │ │ FRED ✓││
│  │ $4,561.50        │ │ 252D LEVELS│ │ ZONE    │ │ C· NEUTRAL     │ │ GPR  ✓││
│  │ −157.20 (−3.32%) │ │ −0.07      │ │ R2 MOD  │ │ V· STRETCHED   │ │ ETF  ✓││
│  │ H 4615 L 4524    │ │ 504d −0.31 │ │ trap    │ │                │ │ COT  ✓││
│  │ O 4615           │ │ SUSPENDED  │ │heuristic│ │ overall: MIXED │ │ UW   ✓││
│  └──────────────────┘ └────────────┘ └─────────┘ └────────────────┘ └──────┘│
└──────────────────────────────────────────────────────────────────────────────┘

┌─ TIER 2: LENS 1 · STRUCTURAL FLOW ───────────────────────── FAVORABLE ──────┐
│  Lead chart — GLD holdings vs gold price (2020-present)                      │
│  [hand-rolled SVG via lib/svgChart.ts; dual-axis if confined to one panel]   │
│                                                                              │
│  ┌─CB RES Δ12M─┐ ┌─ETF FLOW──┐ ┌─COMEX 20D─┐ ┌─COT MM─┐ ┌─UW SKEW─┐ ┌─FX───┐│
│  │ +210 t      │ │ −12 t/30D │ │ +14% ROC  │ │ 72%ile │ │ +1.2σ   │ │ DXY  ││
│  │ strategic   │ │ stabilize │ │ rebuild   │ │ tight  │ │ 25Δ put-│ │ +0.6σ││
│  │ 52w 78%ile  │ │ 30D       │ │ inventory │ │ 4w Δ   │ │  call   │ │ weak ││
│  │             │ │           │ │           │ │ +0.18σ │ │ persist │ │      ││
│  └─────────────┘ └───────────┘ └───────────┘ └────────┘ └─────────┘ └──────┘│
│                                                                              │
│  Posture text: "Structural bid intact. CB strategic accumulators ran ~210t  │
│  trailing 12m. ETF outflows stabilizing. COMEX registered ↑ from inventory  │
│  build. UW 25Δ skew elevated (persisted only — no model promotion in A1)."  │
└──────────────────────────────────────────────────────────────────────────────┘

┌─ TIER 3: LENS 2 · CYCLICAL POSTURE ────────────────────────── NEUTRAL ──────┐
│  Greyed when gauge SUSPENDED. Article-zone badge always carries "heuristic". │
│                                                                              │
│  ┌─REAL RATE──┐ ┌─USD TREND──┐ ┌─GPR───────┐ ┌─INF EXP─┐  ARTICLE ZONE     │
│  │ DFII10     │ │ DXY 102.1  │ │ 371 +3.2  │ │ T5YIFR  │  R2 · MODERATE   │
│  │  1.72%     │ │ 60d −0.4σ  │ │ 64%ile    │ │  2.28%  │  TRAP            │
│  │ ZONE B     │ │ neutral    │ │ elevated  │ │ +0.01   │  [heuristic, not  │
│  │ 60d +12bps │ │            │ │           │ │ 48%ile  │   yet calibrated] │
│  └────────────┘ └────────────┘ └───────────┘ └─────────┘                    │
│                                                                              │
│  ┌─ Two-force narrative ─────────────────────────────────────────────────┐  │
│  │ Discount-rate channel ↑ tightening — would press gold                 │  │
│  │ Hedge-demand channel  ↓ subdued vol — no panic bid                    │  │
│  └───────────────────────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────────────────────┘

┌─ TIER 4: LENS 3 · VALUATION OVERLAY ───────────────────── STRETCHED ────────┐
│  ⚠ NEVER A SIZING INPUT — tail-risk awareness only.                          │
│  Authoritative reference: docs/research/gold-sdf-framework/07-valuation-overlay.md │
│                                                                              │
│  ┌─GOLD/CPI──┐ ┌─GOLD/M2──┐ ┌─GOLD/OIL──┐ ┌─GOLD/SPX──┐                    │
│  │ 92%ile    │ │ 78%ile   │ │ 89%ile    │ │ 64%ile    │                    │
│  │ SEVERE    │ │ HIGH     │ │ SEVERE    │ │ MODERATE  │                    │
│  └───────────┘ └──────────┘ └───────────┘ └───────────┘                    │
│                                                                              │
│  Posture text: "Mean-reversion risk SEVERE on inflation-adjusted basis.     │
│  Lens 3 is context, not a sizing signal."                                   │
└──────────────────────────────────────────────────────────────────────────────┘

┌─ TIER 5: DECOMPOSITION + CORRELATION HISTORY ───────────────────────────────┐
│  Two-column split, each panel is `AnalyticalSeriesPanel` framed.             │
│                                                                              │
│  ┌─LENS DECOMPOSITION─────────────────┐ ┌─CORRELATION HISTORY─────────────┐ │
│  │ Horizontal bar chart, hand-rolled  │ │ Multi-series line chart.        │ │
│  │ SVG. One row per sub-factor of     │ │ Rolling correlation windows:    │ │
│  │ each lens, contribution-signed.    │ │  60d · 126d · 252d · 504d       │ │
│  │ Bar color: --positive / --negative.│ │ Series:                         │ │
│  │ Example:                           │ │  gold ↔ DFII10 (primary)        │ │
│  │   CB Δ12M    ████████░░  +1.4σ     │ │  gold ↔ DXY    (secondary)      │ │
│  │   COMEX ROC  ███░░░░░░░  +0.6σ     │ │  gold ↔ GPR    (secondary)      │ │
│  │   ETF flow   ░░░░░░░░██  −0.2σ     │ │ Reference band: pre-2022 mean   │ │
│  │   COT MM     ███████░░░  +1.2σ     │ │ ± 1σ overlay                    │ │
│  │   UW skew    ████░░░░░░  +0.8σ     │ │                                 │ │
│  │   DXY        ░░░░░░░░█░  −0.4σ     │ │ This is the visual evidence of  │ │
│  │   GPR        ████████░░  +1.4σ     │ │ the post-2022 regime change.    │ │
│  │ (lens labels grouped by color)     │ │                                 │ │
│  └────────────────────────────────────┘ └─────────────────────────────────┘ │
│                                                                              │
│  Note: decomposition is over heuristic z-scores, not model attributions.     │
│  No SHAP, no XGBoost, no IC — those are Phase A3 surfaces.                  │
└──────────────────────────────────────────────────────────────────────────────┘

┌─ DATA AUDIT FOOTER (always at page bottom) ─────────────────────────────────┐
│  GOLD COMPASS · LENS HEURISTICS · v1     · obs_date 2026-05-17              │
│  Posture computed_at: 2026-05-17T21:00:00-04:00 (first-computed)             │
│  Inputs used (vintages):                                                     │
│    DFII10@2026-05-17 · T5YIFR@2026-05-17 · CPI@2026-04 (rel 2026-05-14)     │
│    WGC CB@2026-04 (rel 2026-05-08) · COT@2026-05-13 (rel 2026-05-16)        │
│    UW skew@2026-05-17 (persisted, no model) · GPR@2026-05-17                │
│  [Open replay for any date] [Download inputs JSON]                           │
└──────────────────────────────────────────────────────────────────────────────┘
```

The data-audit footer is the user-facing surface of the replay scaffold. It tells the user exactly which vintages produced today's posture — meeting the Codex "as-of labels everywhere" requirement. The footer is also the natural place to surface the v1 wordmark `LENS HEURISTICS · v1` (replacing the reference's `XGBoost · 8因子` claim, which would be a lie in A1).

**Posture chip color coding** (used on every lens header and on per-lens posture in the KPI strip):

| Posture | Color token | When |
|---|---|---|
| `FAVORABLE` | `--positive` (#05ad98) | Lens's heuristic favors the lens thesis |
| `NEUTRAL` | `--text-secondary` (#94a3b8) | No clear lens read |
| `STRETCHED` | `--warning` (#f5a623) | Lens 3 only — valuation in upper percentiles |
| `SUSPENDED` | `--text-muted` (#475569) | Lens currently not actionable (e.g., gauge below threshold for Lens 2) |
| `DEGRADED` | `--negative` (#e85d6c) | Source data stale or absent — lens unreliable |

`STRETCHED` exists only for Lens 3 — Lens 1 and Lens 2 never carry it because their stretched states are conditional on the gauge (Lens 1) or the article zone (Lens 2), not a percentile threshold.

### 8.3 Component breakdown

```
web/components/gold/
├── GoldCompassLayout.tsx           # top-level 12-col grid shell, five tiers
├── GoldCompassHeader.tsx           # title + regime chips + replay picker
│
├── kpi/                            # Tier 1 strip — five canonical Tile-shaped cards
│   ├── SpotPriceCard.tsx           # XAU/USD with H/L/O, signed delta colored
│   ├── CorrelationGaugeCard.tsx    # gauge 252d + 504d sub-value, state chip
│   ├── RegimeBadgeCard.tsx         # R1/R2/R3 from cyclical zones (heuristic badge)
│   ├── LensesOverallCard.tsx       # three posture chips stacked S·C·V + overall
│   └── DataFreshnessCard.tsx       # per-source ✓/⚠/✗ glyphs + last-fetch age
│
├── lens1/                          # Tier 2 — structural flow
│   ├── StructuralPanel.tsx         # panel shell with header chip
│   ├── GoldHoldingsVsPriceChart.tsx  # lead chart, dual-axis SVG
│   ├── CbReservesCard.tsx          # CB Δ12M tile
│   ├── EtfFlowCard.tsx             # ETF 30d net tile
│   ├── ComexRegimeCard.tsx         # COMEX 20d ROC + LBMA momentum
│   ├── CotPositioningCard.tsx      # MM net %ile + 4w Δ
│   ├── UwSkewCard.tsx              # 25Δ skew tile (persist-only badge)
│   ├── FxBasketCard.tsx            # DXY trend / XAU local premia
│   └── StructuralPostureText.tsx   # narrative text under cards
│
├── lens2/                          # Tier 3 — cyclical posture
│   ├── CyclicalPanel.tsx
│   ├── RealRateCard.tsx            # DFII10 + zone badge
│   ├── UsdTrendCard.tsx            # DXY trend tile
│   ├── GprCard.tsx                 # GPR daily + percentile
│   ├── InfExpCard.tsx              # T5YIFR + 60d change
│   ├── ArticleZoneCard.tsx         # R1/R2/R3 zone with heuristic badge
│   └── TwoForceNarrative.tsx       # discount-rate vs hedge-demand text
│
├── lens3/                          # Tier 4 — valuation overlay
│   ├── ValuationPanel.tsx          # panel with NEVER-A-SIZING-INPUT callout
│   ├── ValuationFlagCard.tsx       # gold/CPI · gold/M2 · gold/oil · gold/SPX
│   └── ValuationPostureText.tsx
│
├── decomposition/                  # Tier 5 left
│   ├── LensDecompositionPanel.tsx  # AnalyticalSeriesPanel wrapper
│   └── DecompositionBars.tsx       # hand-rolled horizontal SVG bars
│
├── correlation/                    # Tier 5 right
│   ├── CorrelationHistoryPanel.tsx # AnalyticalSeriesPanel wrapper
│   └── CorrelationLineChart.tsx    # multi-window SVG line chart
│
├── DataAuditFooter.tsx             # always-bottom footer with vintages
├── ReplayDatePicker.tsx            # in header chip, opens /gold/replay/[date]
└── chips/                          # shared inline chips
    ├── PostureChip.tsx             # FAVORABLE / NEUTRAL / STRETCHED / SUSPENDED / DEGRADED
    ├── HeuristicBadge.tsx          # small "[heuristic, not yet calibrated]" tag
    └── PersistOnlyBadge.tsx        # "persist-only, no model promotion in A1"
```

All charts hand-rolled SVG via `lib/svgChart.ts` per the repo convention. Tooltips include vintage information (`obs_date` and `as_of`).

**Reuse from existing repo:**

- `Tile` shape (10/22/11px mono): copy the inline pattern from `components/stock/panels/VolMetricsCard.tsx`. Do not extract a shared `Tile` yet — repo convention is "inline until 3+ callers need it"; GOLD COMPASS uses it many times, but it's its own subtree, so extract only `gold/chips/Tile.tsx` local to gold.
- `AnalyticalSeriesPanel` (titled SVG frame): import directly from `components/stock/panels/`.
- `svgChart.ts` helpers (`linearScale`, `finiteDomain`, `pathFromPoints`): used by the lead chart, decomposition bars, and correlation history.
- Formatters (`fmtPct`, `fmtSigned`, `fmtDecimal`): used everywhere a numeric value is rendered.

**Client / server split:**

- `web/app/gold/page.tsx` is an RSC — fetches `/api/gold/state` server-side, passes data as props to `GoldCompassLayout`.
- `GoldCompassLayout`, all `kpi/*`, `lens1/*`, `lens2/*`, `lens3/*`, `decomposition/*`, `correlation/*` components are server components (pure props in, SVG out).
- `ReplayDatePicker` is the only client component — needs router navigation on date change.
- The replay route `web/app/gold/replay/[date]/page.tsx` is RSC, fetches `/api/gold/replay?as_of=...`, renders the **same** `GoldCompassLayout` with the historical posture row.

**Plan realignment required — referenced from §15.** The companion plan (`docs/superpowers/plans/2026-05-16-gold-phase-a1-plan.md`) was written before this layout was finalised. Plan tasks 28–34 refer to the older `ThreeLensLayout` / `StructuralPanel` / `CyclicalPanel` / `ValuationPanel` / `CorrelationGaugeBanner` / `DataAuditFooter` component names and the simpler vertical three-lens structure. Before web implementation begins, those plan tasks must be rewritten to match the new component subtree above (KPI strip, lens1/, lens2/, lens3/, decomposition/, correlation/). Specifically:

- Task 28 (page route + ThreeLensLayout) → page route + `GoldCompassLayout` + KPI strip (Tier 1)
- Task 29 (CorrelationGaugeBanner) → split into `kpi/CorrelationGaugeCard` + `kpi/RegimeBadgeCard` + `kpi/LensesOverallCard` + `kpi/SpotPriceCard` + `kpi/DataFreshnessCard`
- Task 30 (StructuralPanel + sub-cards) → `lens1/*` subtree including lead chart and 6 cards
- Task 31 (CyclicalPanel + ArticleZoneCard) → `lens2/*` subtree (4 cards + zone + two-force)
- Task 32 (ValuationPanel + DataAuditFooter) → split into `lens3/*` subtree and standalone `DataAuditFooter.tsx`
- New tasks needed for `decomposition/*` (Tier 5 left) and `correlation/*` (Tier 5 right)
- Task 33 (lead chart) becomes part of `lens1/GoldHoldingsVsPriceChart.tsx` (already aligned)
- Task 34 (replay route) — unchanged in scope, but must instantiate `GoldCompassLayout` not `ThreeLensLayout`

The data-layer tasks (1–25), API tasks (20–22), and acceptance test (36) are **unchanged** by this UI revision — the layout-only refactor doesn't touch backend contracts.

### 8.4 Posture-language enforcement

All UI copy uses **posture / risk / scenario** language, not **recommendation / position / size / prediction**. The reference dashboard (`gold-monitor-delta.vercel.app`) violates this discipline freely; GOLD COMPASS A1 must not.

**Banned in v1 UI copy and component literals:**

| Category | Banned strings |
|---|---|
| Sizing imperatives | `buy`, `sell`, `long`, `short`, `做多`, `做空` (as imperatives, not in compound phrases like "long-horizon") |
| Sizing nouns | `position size`, `recommended size`, `allocate %`, `position heat`, `仓位` (numeric weight) |
| Execution verbs | `trade`, `execute`, `enter`, `exit`, `take profit`, `stop loss` |
| Model claims | `predicted return`, `today's signal`, `signal: long/short`, `IC: X`, `SHAP`, `XGBoost`, `8因子`, `预测收益`, `今日信号` |
| Backtest claims | `equity curve`, `Sharpe`, `Calmar`, `win rate`, `max drawdown`, `current drawdown`, `净值曲线`, `回测账户` |
| Performance claims | `+X% trailing`, `+X% YTD return`, any forward-looking percentage that isn't a posture probability |

**Allowed in v1:**

- Lens posture states: `FAVORABLE`, `NEUTRAL`, `STRETCHED`, `SUSPENDED`, `DEGRADED`
- Article zones: `R1 LOW-INFLATION`, `R2 MODERATE-TRAP`, `R3 UNANCHORED` — always with `[heuristic, not yet calibrated]` badge
- Narrative phrases: "structural bid intact / weakening", "cyclical framework operative / suspended", "mean-reversion risk", "informative only", "tail-risk awareness only"
- Vintage / freshness language: "ingested at", "released at", "stale by N days"
- Posture-context labels: `A POSTURE CONTEXT (long-horizon)`, `B POSTURE CONTEXT (event-hedge)` — narrative, not weights
- Compound phrases where the banned word is grammatically necessary and non-imperative: `long-horizon`, `short-term volatility`, `take a position` only inside disclaimer text that ALSO renders the `[INFORMATIVE ONLY]` chip

**Enforcement:**

- `web/lib/copy-rules.ts` exports `BANNED_POSTURE_LANGUAGE: readonly string[]` and `lintFileLiterals(source: string): LintFinding[]`.
- The lint helper is wired into a Vitest unit test (`web/tests/unit/posture-language.test.ts`) that scans every `.tsx` file under `web/components/gold/` and `web/app/gold/` for banned substrings in string literals.
- CI (`npm run test`) runs the unit test → fails the build on any violation.
- Allow-list: the test accepts the `BANNED_POSTURE_LANGUAGE` array file itself, and any `*.test.ts` file (which intentionally references banned strings for negative-case coverage).
- Phase A1 acceptance: lint passes; one negative test confirms it would catch a regression (intentionally inject `"buy gold"` into a fixture file → assert lint fails).

The lint is intentionally substring-based (not AST-based). False positives are resolved either by rewording or by adding a directional comment `// posture-lint-ignore: <reason>` on the line — this preserves the discipline while letting compound phrases through. The directive is permitted only inside `disclaimer.tsx`-style components and is itself checked by CI (count of ignores cannot exceed 5 file-wide; growth is a code-review smell).

---

## 9. Replay / audit scaffold — load-bearing detail

This is the feature that distinguishes Option A-prime from Option A. Three concrete pieces:

### 9.1 Vintage-aware inputs

Every row in `macro_series_daily`, `etf_holdings_daily`, `exchange_inventory_daily`, `cb_gold_reserves_monthly`, `cot_gold_weekly`, `uw_gold_options_daily` carries:

- `obs_date` (or `obs_month`) — the day the value pertains to
- `as_of` — when we ingested it
- `release_date` (where applicable) — when it was publicly available

PK includes `as_of` so re-pulls don't overwrite history. This is the foundation: we can always reconstruct what was knowable on any given decision date.

### 9.2 Inputs provenance in posture rows

`gold_posture_daily.inputs_jsonb` records, for every signal that contributed to a posture row, the `(series_id, obs_date, as_of)` triple that was consumed. This means:

- The data-audit footer can show the user *exactly which vintages* produced their current view.
- Replay queries can reconstruct an exact past posture deterministically.
- Phase A3 backtest can read posture history as-computed-on-the-day, with no data leakage.

### 9.3 Replay endpoint discipline

`GET /api/gold/replay?as_of=2026-04-15` returns the `gold_posture_daily` row where `obs_date = '2026-04-15'`, choosing the **first** `computed_at` for that obs_date (so we get the posture as it was first computed, not any later recomputation). If a posture row gets recomputed (e.g., due to a data correction), the original row is preserved; the replay returns the original.

This is intentionally stricter than "current state of input series." The replay scaffold proves we can answer: "what did the cockpit say on day X?" — not "what would the cockpit say today if we replayed day X's inputs with today's transformation logic." Phase A3 will need both, but A1 ships the first.

### 9.4 Acceptance test

A specific acceptance test for A1: pick any 5 historical dates in the rolling 30-day window after A1 ships. For each date:

1. Pull the original `gold_posture_daily` row at that obs_date.
2. Reconstruct it by re-running `gold_posture_compute` with `as_of` filtered to "data available by that obs_date + 1 day".
3. Assert the reconstructed posture matches the original byte-for-byte (excluding `computed_at`).

If this test passes, the audit scaffold is operative. If it fails, the replay scaffold has a leak and A1 is not done.

---

## 10. Engineering estimate

Per the existing repo convention (one method per query, typed Pydantic responses, idempotent migrations, telemetry-wrapped HTTP). Web-cockpit estimate revised upward in this draft to reflect the GOLD COMPASS 5-tier layout (9 web tasks across kpi/ lens1/ lens2/ lens3/ decomposition/ correlation/ subtrees per spec §8.3) rather than the 7-task vertical three-lens layout in the prior draft.

| Component | Plan task(s) | Engineering days |
|---|---|---|
| `sources/fred.py` + telemetry + tests | 2 | 2-3 |
| `sources/gpr.py` + tests | 3 | 1 |
| `sources/etf_holdings.py` (4 funds) + tests | 4 | 2-3 |
| `sources/comex.py` (HTML/JSON parse) + tests | 5 | 1-2 |
| `sources/lbma.py` + tests | 6 | 0.5 |
| `sources/wgc_cb.py` + bucket config + tests | 7 | 1-2 |
| `sources/cftc_cot.py` + tests | 8 | 1-2 |
| UW gold-options snapshot extension in `sources/uw.py` + tests | 9 | 1-2 |
| Postgres migrations (8 tables + GOLD COMPASS UI columns on `gold_posture_daily`) | 1 | 1-1.5 |
| `storage/repository.py` extensions (one method per query) | 10-13 | 2-3 |
| `cards/regime_gauge.py` + tests | 14 | 1 |
| `cards/structural_flow.py` (incl. headline z-score exports for decomposition) + tests | 15 | 2-3 |
| `cards/cyclical_zones.py` + tests | 16 | 1-2 |
| `cards/valuation.py` + tests | 17 | 1 |
| Pydantic models (`models.py`) — expanded GOLD COMPASS shape | 18 | 1-1.5 |
| `reports/gold_posture.py` orchestrator (incl. spot / data_freshness / decomposition / correlation history helpers) + tests | 19 | 2-3 |
| `api/routers/gold.py` (5 endpoints) + tests | 20-22 | 2-3 |
| `worker/scheduler.py` job additions + tests | 23-25 | 1-2 |
| OpenAPI type regeneration (`web/lib/types.ts`) | 26 | 0.25 |
| Posture-language lint helper (`web/lib/copy-rules.ts`) | 27 | 0.5 |
| Web cockpit — GOLD COMPASS subtree: | **28-36** | **10-15** |
|   · Task 28 shell + chips | 28 | 0.5-1 |
|   · Task 29 Tier 1 KPI strip (5 cards) | 29 | 1-1.5 |
|   · Task 30 Tier 2 Lens 1 panel + 6 sub-cards | 30 | 1.5-2 |
|   · Task 31 Tier 3 Lens 2 panel + 4 cards + zone + two-force | 31 | 1-1.5 |
|   · Task 32 Tier 4 Lens 3 panel + DataAuditFooter | 32 | 1-1.5 |
|   · Task 33 Tier 5 decomposition panel + bars | 33 | 1-1.5 |
|   · Task 34 Tier 5 correlation history panel + chart | 34 | 1-1.5 |
|   · Task 35 lens1/GoldHoldingsVsPriceChart (lead visual) | 35 | 1 |
|   · Task 36 Replay route + ReplayDatePicker | 36 | 0.5-1 |
| Posture-language CI lint integration | 37 | 0.5-1 |
| Replay-scaffold acceptance test | 38 | 0.5-1 |
| **Total** | **38 tasks** | **~35-52 engineer-days = 7-10 calendar weeks at 1 engineer; 4-6 weeks at 2 engineers parallelising the data layer + UI** |

Matches the Option A-prime Phase A1 estimate after the visual-design adjustment. Subagent-driven execution can compress wall-clock further on the web tier where the 9 tasks are largely independent within a tier (cards within Lens 1, cards within Lens 2, etc).

---

## 11. Testing strategy

- **Unit tests** (pytest, mirrors existing repo conventions): per-source-module HTTP mocking, per-card pure-function tests with fixture inputs, per-repository-method query tests against `pytest-postgresql`.
- **Integration tests**: end-to-end posture computation against a seeded test database. Replay acceptance test (§9.4).
- **Web tests** (Vitest): component snapshot tests for each panel under each gauge state; e2e Playwright test that hits `/gold` and asserts headline gauge state matches API.
- **Lint**: the posture-language enforcement rule (§8.4) runs as part of `npm run lint`.
- **Live API tests**: marked `live` per repo convention, require keys, default `pytest` excludes. Each new source has at least one live smoke test.

---

## 12. Acceptance criteria

A1 is done when **all** of these hold:

1. All eight scheduled jobs run cleanly for 7 consecutive days against the production data sources.
2. `gold_posture_daily` accumulates one row per day with `inputs_jsonb` provenance present.
3. The replay acceptance test (§9.4) passes for 5 historical dates.
4. `GET /api/gold/state` returns a well-formed `GoldStateResponse` containing posture text for all three lenses.
5. The cockpit page at `/gold` renders successfully and the data-audit footer shows correct vintage information.
6. The posture-language lint rule passes (no banned strings in component literals).
7. `cd web && npm run gen:types` regenerates types cleanly from the OpenAPI surface.
8. Migration files are idempotent (re-running `bash scripts/migrate.sh` is a no-op).
9. All `pytest` and `vitest` test suites pass.
10. Codex review of the implementation lands without P0 findings (per repo's `/codex-review` gate convention).

---

## 13. Risks and open decisions for Phase A2

A1 ships with deliberate placeholders for these — they are resolved in Phase A2.

### A1 ships as configurable / placeholder

- **Correlation gauge thresholds** (operative / partial / suspended bands). Default per [docs/research/gold-sdf-framework/04-three-layer-architecture.md](../../research/gold-sdf-framework/04-three-layer-architecture.md), config-driven, A2 calibrates empirically.
- **Article-zone thresholds** for CPI / T5YIFR. Default article values, labeled "heuristic" in UI, A2 calibrates against multi-indicator anchoring basket per [docs/research/gold-sdf-framework/10-open-research-questions.md Q24](../../research/gold-sdf-framework/10-open-research-questions.md).
- **CB bucket assignments** (which countries are strategic vs tactical vs diversifier). Config-driven, can revise without migration.
- **Posture narrative templates**. Hand-written deterministic phrasing in A1; A2 may add Codex-CLI-generated narratives (using existing Trade Insights AI pattern) if useful.

### A1 explicitly defers

- **Internal replication of the post-2022 correlation collapse** with formal break tests — Phase A2 (Q20).
- **Target-definition lock-in** (GLD vs LBMA vs GC=F as canonical gold reference) — Phase A2 (Q26).
- **Benchmark comparison definitions** — Phase A2 (Q29).
- **Validation basket** (deflated Sharpe, PBO, regime-conditional) — Phase A3.

### A1 risks worth flagging up-front

- **Data-source robustness**: FRED CSV endpoint and free CME/LBMA reports occasionally rate-limit or change format. Mitigation: telemetry on every fetch, alarming on 5xx / parse failure, manual override path.
- **WGC monthly CSV format drift**: WGC has changed their goldhub data layout twice in recent years. Mitigation: pin a schema check in the ingestor; fail loudly on shape change rather than silently writing nulls.
- **UW options data volume**: persisting GLD/GDX/IAU chains daily is non-trivial in row count. Acceptance: estimate row counts during sizing, partition `uw_gold_options_daily` by month if needed.
- **Posture-language lint false positives**: aggressive lint rules sometimes flag legitimate copy. Mitigation: rule covers component literals only, with explicit allowlist for academic-source quotes; lint exit code 0 only required for new components.

---

## 14. Self-review

Inline review pass before requesting user review:

- **Placeholder scan**: One genuine "TBD" in §5.8 (dealer-gamma convention). Acceptable for Phase A1 — convention is settled during implementation when we see UW chain data shape; not load-bearing for A1 design.
- **Internal consistency**: Architecture diagram (§3), data model (§4), API surface (§6), and UI layout (§8) all agree on the three-lens organization and on the source-list. No contradictions found.
- **Scope check**: One sub-project (Phase A1) per the Codex-recommended Option A-prime. Engineering estimate (~5-7 weeks) matches the option's stated cost. Not too large.
- **Ambiguity check**: §4.7 `uw_gold_options_daily` `dealer_gamma_est` "raw or normalized; convention TBD" — flagged as deferred-decision. §7.5 narrative-template approach explicitly "no LLM in A1" with hand-written templates — disambiguated.
- **Cross-refs**: 11 distinct links to research-foundation files and the Codex review. Each cross-ref is to a real file in this worktree.

---

## 15. Next step

After user review of this spec:

1. **If approved**: the companion plan exists at `docs/superpowers/plans/2026-05-16-gold-phase-a1-plan.md`. Before executing it, re-do plan tasks 28–34 per the realignment note at the end of §8.3 (the plan was written against the older three-lens vertical layout; this spec now specifies the GOLD COMPASS five-tier layout). Data-layer tasks (1–25), API tasks (20–22), and acceptance test (36) are unchanged.
2. **If changes requested**: revise spec inline, re-run §14 self-review, re-request user review.
3. **If a different scope decision (Option A or B)** — revert to research foundation Q13 and re-spec accordingly.

Phase A2 spec and Phase A3 spec are explicitly deferred — written *after* A1 ships, when we have empirical data and concrete model-readiness signal to spec from.
