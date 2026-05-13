# Volatility Tab v2 — Merge VRP, add chart grid + analytical row (Design Spec)

**Status:** Draft for review
**Author:** brainstorming session, 2026-05-13
**Supersedes:** the per-ticker VRP tab (`web/components/stock/tabs/VrpTab.tsx`) and the today's minimal Volatility tab (`web/components/stock/tabs/VolatilityTab.tsx`)
**Companion notes:**
- Reference visuals: Futu term-structure + smile + IV/HV history (mobile screenshots), xenon analytical-time-series and regime-quadrant panels (provided in conversation)
- Standing rule honoured: every series this spec computes is written back to Postgres (`schema uw_scan`) — no in-memory-only results.

---

## 1. Goals

1. **Merge** the existing `Volatility` and `VRP` tabs into a single `Volatility` tab. The merged tab is the single home for all IV/RV/VRP/skew/term/smile/correlation analytics for one ticker.
2. **Promote** the header metrics row to the styling shown in the reference (`VOLATILITY SURFACE` card) — same `MetricGrid` density as today, with a VRP signal badge inline and the rationale note rendered below the card.
3. **Add a 2×2 primary chart grid** — Term Structure, Smile, HV/IV history, IV %ile distribution.
4. **Add an analytical row** of per-stock analogues to the CBOE VIX/VVIX/COR1M/regime-quadrant panels: IV vs IV-of-IV, RV vs SPY-correlation 1m, regime quadrant (RVOL %ile × SPY corr), normalised divergence (IV-z vs RV-z).
5. **Add a full-width VRP spread panel** at the bottom (bars + smoothed line, image-19 reference style).
6. **Persist every derived series** (VRP daily, IV-of-IV daily, stock-SPY correlation daily, smile snapshots) into Postgres so subsequent loads read from DB and the data can power future history/backtest features.
7. Backfill historical depth on first request: pull UW's `/volatility/realized` and `/historical-risk-reversal-skew` (both natively historical endpoints), plus a one-time SPY OHLC ingest for the correlation panel.

## 2. Non-goals

- **Market-wide indices (VIX, VVIX, COR1M).** Out of scope — those are CBOE indices, not in the UW dataset; we use **per-stock analogues** instead (IV-of-IV, stock-vs-SPY correlation). Adding the actual CBOE series is a possible follow-up but not in this spec.
- **Real-time streaming.** Same as the watchlist rework — page-load fetch is sufficient.
- **Cross-stock comparisons / rankings on this tab.** This is a single-stock tab. Universe-level vol screening stays in the scanner.
- **Backtesting / strategy P&L on z-score signals.** We persist the series; downstream consumers will be built later.
- **Light theme.** Dark mode only.
- **Trade-plan generation from VRP signal.** That belongs in the Trade Plan tab; here we only render the signal.

## 3. Final tab layout

```
┌─ HEADER METRICS CARD ───────────────────────────────────────────────────────┐
│  VOLATILITY                                                                 │
│  IV (ATM)   RV   IV Rank   IV Rank 1y           ┌─ VRP +0.42 BUY-VOL ─┐    │
│  IV 52w Lo  IV 52w Hi  RV 52w Lo  RV 52w Hi                                 │
│  IV %ile 30d   Implied Move 30d   Skew 25Δ                                  │
│  Note: IV rich vs RV — favours short premium…                               │
└─────────────────────────────────────────────────────────────────────────────┘

┌─ TERM STRUCTURE ────────────────┐ ┌─ SMILE ─────────────────────────────────┐
│  IV by DTE                      │ │  IV by strike                           │
│  4 lines: ATM−2 / ATM−1 / ATM / │ │  4 lines: nearest 4 expiries (0/7/30/60d) │
│  ATM+1 strikes                  │ │                                         │
└─────────────────────────────────┘ └─────────────────────────────────────────┘

┌─ HV / IV CHART ─────────────────┐ ┌─ IV %ILE DISTRIBUTION ──────────────────┐
│  Daily IV + RV, ~365 days       │ │  Histogram of IV over last 365 days     │
│  Earnings markers (•) on dates  │ │  Current IV marked with vertical line   │
│  IV = blue, RV = orange (Futu)  │ │  Percentile labelled top-right          │
└─────────────────────────────────┘ └─────────────────────────────────────────┘

──── ANALYTICAL TIME SERIES ─────────────────────────────────────────────────

┌─ IV / IV-OF-IV ─────────────────┐ ┌─ RV / SPY-CORR-1M ──────────────────────┐
│  Image-18-left style            │ │  Image-18-right style                   │
│  IV = teal (left axis)          │ │  RV = orange (left axis)                │
│  IV-of-IV = purple (right axis) │ │  SPY-corr-21d = pink (right axis)       │
└─────────────────────────────────┘ └─────────────────────────────────────────┘

┌─ REGIME QUADRANT ───────────────┐ ┌─ NORMALISED DIVERGENCE ─────────────────┐
│  Image-19-left style            │ │  Image-19-right style                   │
│  X = RVOL %ile, Y = SPY-corr    │ │  IV-z vs RV-z (20-session)              │
│  20-session scatter, latest big │ │  Headline σ top-right                   │
│  4 quadrant labels:             │ │  IV-z = orange, RV-z = pink             │
│  • Goldilocks (low/low)         │ │                                         │
│  • Stock Picker (high/low)      │ │                                         │
│  • Fragile Calm (low/high)      │ │                                         │
│  • Systemic Panic (high/high)   │ │                                         │
│  State key tiles below          │ │                                         │
└─────────────────────────────────┘ └─────────────────────────────────────────┘

┌─ VRP SPREAD (full width) ───────────────────────────────────────────────────┐
│  Image-19-bottom style                                                      │
│  Bars: raw (IV − RV) per day, coloured by sign (positive = teal, neg = red) │
│  Line: smoothed VRP overlay                                                 │
│  Headline +0.48 pts, compressing −0.80 pts                                  │
└─────────────────────────────────────────────────────────────────────────────┘
```

## 4. Data sources and persistence

### 4.1 Already-stored series (read-only consumers)

| Table | Used by panels |
|---|---|
| `uw_scan.volatility_stats_history` | Header card metrics (IV 52w hi/lo, RV 52w hi/lo, IV rank) |
| `uw_scan.realized_volatility_history` | HV/IV chart, IV %ile distribution, VRP spread, IV-of-IV, divergence overlay |
| `uw_scan.iv_term_snapshots` | Term Structure chart |
| `uw_scan.interpolated_iv_snapshots` | Header IV (ATM), term structure ATM line |
| `uw_scan.risk_reversal_skew_history` | Header Skew 25Δ metric |

### 4.2 New persistence (added by this spec)

```sql
-- Daily SPY (or any benchmark) close prices, for correlation calc.
-- One time backfill via massive.io OHLC source; daily update via worker.
CREATE TABLE IF NOT EXISTS uw_scan.index_ohlc_daily (
    ticker      TEXT NOT NULL,
    market_date DATE NOT NULL,
    open        NUMERIC,
    high        NUMERIC,
    low         NUMERIC,
    close       NUMERIC NOT NULL,
    volume      BIGINT,
    inserted_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (ticker, market_date)
);
-- Seeded with SPY back ~3 years.
-- Future: any other index/ETF needed (XLK/QQQ/etc).

-- Per-strike IV by expiry — the smile chart's source. Derived from greeks
-- endpoint pull. Persisted snapshot so the smile renders without re-hitting UW.
CREATE TABLE IF NOT EXISTS uw_scan.iv_smile_snapshots (
    ticker      TEXT NOT NULL,
    market_date DATE NOT NULL,
    expiry      DATE NOT NULL,
    strike      NUMERIC NOT NULL,
    iv          NUMERIC,  -- avg(call_iv, put_iv) when both present
    inserted_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (ticker, market_date, expiry, strike)
);

-- Derived daily VRP series. (IV − RV) with rolling z-score.
-- Materialised on read but persisted for fast re-load and downstream consumers.
CREATE TABLE IF NOT EXISTS uw_scan.vrp_daily (
    ticker      TEXT NOT NULL,
    market_date DATE NOT NULL,
    iv          NUMERIC,
    rv          NUMERIC,
    vrp         NUMERIC,         -- iv − rv
    vrp_z_20    NUMERIC,         -- (vrp − rolling_mean_20) / rolling_std_20
    inserted_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (ticker, market_date)
);

-- Per-stock 1m correlation to SPY (and IV-of-IV) — daily.
CREATE TABLE IF NOT EXISTS uw_scan.stock_analytics_daily (
    ticker      TEXT NOT NULL,
    market_date DATE NOT NULL,
    rvol_21     NUMERIC,         -- realised vol, 21d ann.
    rvol_pctile NUMERIC,         -- 0–100, over trailing 252d
    spy_corr_21 NUMERIC,         -- Pearson(stock_ret, spy_ret) 21d
    iv_of_iv_20 NUMERIC,         -- stdev(daily IV) over 20d, annualised
    inserted_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (ticker, market_date)
);
```

All four new tables follow the existing `ticker, market_date` PK convention. Backfill writes the same rows that on-demand compute would write — the table is the cache, not a side ledger.

### 4.3 Smile chart fetch

The smile needs per-strike IV across multiple expiries. Reuses the **already-wired** `fetch_greeks(client, repo, run_id, ticker, expiry)` for each of the nearest 4 expiries. The Market Structure tab already calls these for GEX so most data is already on disk in `greeks_by_expiry_strike`. The new `iv_smile_snapshots` materialises just `iv = avg(call_volatility, put_volatility)` per (date, expiry, strike) from that table — no extra UW calls when the GEX worker has run today.

If the freshest available data is stale (>1 trading day old), the API endpoint kicks off a fresh greeks pull for the nearest 4 expiries before returning. Background pulls are gated by an in-process lock to avoid stampedes.

### 4.4 Backfill on first request

When `GET /api/stock/{ticker}/volatility/series` runs and finds <90 days in `realized_volatility_history`:

```python
# Single call per endpoint — both return historical series.
rv_rows = fetch_realized_volatility(client, repo, run_id, ticker)
skew_rows = fetch_skew(client, repo, run_id, ticker,
                      expiry=nearest_30d_expiry, delta=25)
# Persist via existing insert helpers (idempotent ON CONFLICT DO UPDATE).
```

Then derive `vrp_daily` and `stock_analytics_daily` rows for the ticker by joining IV history + SPY OHLC, and `INSERT … ON CONFLICT DO UPDATE` row by row.

**Backfill runs asynchronously.** First request triggers a background backfill job (kicked off via FastAPI `BackgroundTasks`) and returns **200 immediately** with whatever's already in DB plus a top-level `backfill_status: "running" | "ready" | "failed"` field. Subsequent requests poll every 5s while `backfill_status === "running"`. Once the backfill completes (typically <30s — both UW endpoints return full series in one call each, plus SPY-corr math on cached SPY data), the next poll returns `backfill_status: "ready"` with the full series populated. Backfill writes are idempotent — re-running them does not duplicate. Worker-driven nightly refresh is a follow-up.

### 4.5 SPY OHLC ingest

A one-shot script (`scripts/seed_spy_ohlc.py`) hits the existing `sources/ohlc.py` provider for SPY over the last ~3 years and writes to `index_ohlc_daily`. Worker adds a daily 16:30 ET job to refresh the latest row. This is the only new external source.

## 5. API surface

### 5.1 New endpoint: `GET /api/stock/{ticker}/volatility/series`

```jsonc
// Response shape — added to FastAPI router src/uw_scan/api/routers/stock.py:
{
  "ticker": "TSLA",
  "as_of": "2026-05-13",
  "backfill_status": "ready",   // "running" | "ready" | "failed"
  "header": {
    // Same fields as today's VolatilityProfile + the merged VRP fields
    "iv": 0.5309, "rv": 0.4109, "iv_rank": 21, "iv_rank_1y": 41,
    "iv_low_52w": 0.171, "iv_high_52w": 0.343,
    "rv_low_52w": 0.095, "rv_high_52w": 0.370,
    "iv_percentile_30d": 0.52, "implied_move_30d_perc": 0.046,
    "skew_25d": -0.0079,
    "vrp": 0.42, "vrp_signal": "BUY_VOL", "vrp_note": "IV rich vs RV…"
  },
  "term_structure": [
    // From iv_term_snapshots, latest run_id for ticker.
    {"expiry": "2026-05-15", "dte": 2,
     "by_strike": {"ATM-2": 0.74, "ATM-1": 0.62, "ATM": 0.58, "ATM+1": 0.54}},
    // …4 expiries total
  ],
  "smile": [
    // From iv_smile_snapshots, latest market_date per (expiry, strike).
    {"expiry": "2026-05-15",
     "points": [{"strike": 400, "iv": 0.72}, {"strike": 405, "iv": 0.65}, …]},
    // …4 expiries total
  ],
  "hv_iv_history": [
    // From realized_volatility_history, last 365 days.
    {"date": "2025-11-18", "iv": 0.56, "rv": 0.43},
    …
  ],
  "iv_percentile_distribution": {
    // Histogram bins over the same 365-day IV series.
    "bins": [{"lo": 0.10, "hi": 0.15, "count": 12}, …],
    "current_iv": 0.5309, "current_pctile": 52
  },
  "iv_of_iv": [
    // From stock_analytics_daily, last 90d.
    {"date": "…", "iv": 0.56, "iv_of_iv_20": 0.082},
    …
  ],
  "rv_spy_corr": [
    {"date": "…", "rv": 0.43, "spy_corr_21": 0.31}, …
  ],
  "regime_quadrant": {
    // Last 20 sessions for the scatter.
    "points": [{"date": "…", "rvol_pctile": 45, "spy_corr_21": 0.31}, …],
    "latest": {"rvol_pctile": 50, "spy_corr_21": 0.28,
               "state": "GOLDILOCKS"}  // computed server-side
  },
  "divergence": [
    // Last 20 sessions of z-scored IV and RV (each z'd vs their own 20d window).
    {"date": "…", "iv_z": 0.6, "rv_z": -0.4}, …
  ],
  "divergence_headline": "+0.83σ",
  "vrp_spread": [
    // From vrp_daily, last 30 sessions.
    {"date": "…", "vrp": -5.2, "vrp_z_20": -0.9}, …
  ],
  "vrp_spread_headline": "+0.48 pts, compressing -0.80 pts"
}
```

One round trip from the frontend → one DB read transaction → render. If any series is missing (e.g., new ticker, backfill incomplete), the field is returned as an empty array and the panel shows an empty state. No 500s.

### 5.2 Removed endpoint considerations

Existing `/api/stock/{ticker}` (`SingleStockReport`) continues to include `volatility` and `vrp` blocks unchanged — no breaking change for other consumers (Trade Plan tab, scanner). The new `/volatility/series` endpoint is additive.

## 6. Computation details

### 6.1 VRP daily

```
vrp[d]    = iv[d] − rv[d]
vrp_z_20  = (vrp[d] − mean(vrp[d-19..d])) / stdev(vrp[d-19..d])
```

Computed in Python in a single SQL+pandas pass on first request for any backfill window, then persisted. Subsequent updates compute one row at a time during the daily worker job.

### 6.2 IV-of-IV

```
iv_of_iv_20[d] = stdev(iv[d-19..d]) × sqrt(252)  -- annualised
```

### 6.3 Stock-SPY correlation 21d

```
stock_ret[d] = log(close[d] / close[d-1])     -- from realized_volatility_history.price
spy_ret[d]   = log(spy_close[d] / spy_close[d-1])  -- from index_ohlc_daily
spy_corr_21[d] = corr(stock_ret[d-20..d], spy_ret[d-20..d])
```

### 6.4 RVOL percentile

```
rvol_21[d]     = stdev(stock_ret[d-20..d]) × sqrt(252)
rvol_pctile[d] = percentile_of_value(rvol_21[d], rvol_21[d-251..d])  -- vs trailing 252d
```

### 6.5 Regime state classification

```
state =
    "GOLDILOCKS"        if rvol_pctile < 50 and spy_corr_21 < median_spy_corr_21
    "FRAGILE_CALM"      if rvol_pctile < 50 and spy_corr_21 >= median_spy_corr_21
    "STOCK_PICKER"      if rvol_pctile >= 50 and spy_corr_21 < median_spy_corr_21
    "SYSTEMIC_PANIC"    if rvol_pctile >= 50 and spy_corr_21 >= median_spy_corr_21
```

`median_spy_corr_21` is the trailing 252-day median of `spy_corr_21` for the same ticker — adapts the threshold to each stock's normal correlation regime instead of a global cutoff.

### 6.6 Divergence z-overlay

```
iv_z[d] = (iv[d] − mean(iv[d-19..d])) / stdev(iv[d-19..d])
rv_z[d] = (rv[d] − mean(rv[d-19..d])) / stdev(rv[d-19..d])
divergence[d] = iv_z[d] − rv_z[d]   -- the headline "+0.83σ" is divergence[latest]
```

## 7. Frontend file plan

### 7.1 Routes / tabs

- **Delete:** `web/components/stock/tabs/VrpTab.tsx`
- **Edit:** `web/components/stock/TabBar.tsx` — remove `["vrp", "VRP"]` entry. Order stays: market-structure, volatility, flow, trade-plan, tables.
- **Edit:** `web/app/stock/[ticker]/[tab]/page.tsx` — drop the `vrp` case from the tab-component switch. Any direct `/stock/{ticker}/vrp` URLs return a 404 (acceptable — internal tool, no external links).
- **Rewrite:** `web/components/stock/tabs/VolatilityTab.tsx` — composes the new card + grid + analytical row + bottom panel.

### 7.2 New components

```
web/components/stock/panels/
├── VolMetricsCard.tsx           # Header card: metrics + VRP badge + note
├── TermStructureChart.tsx       # 4 lines: ATM−2 / ATM−1 / ATM / ATM+1 strikes
├── SmileChart.tsx               # 4 lines, one per expiry
├── HvIvChart.tsx                # Daily IV + RV time series (earnings markers deferred — see §11)
├── IvPercentileDistribution.tsx # Histogram of IV over 365d with current IV marker
├── IvOfIvChart.tsx              # IV (teal, L) + IV-of-IV (purple, R) dual-axis
├── RvSpyCorrChart.tsx           # RV (orange, L) + SPY-corr (pink, R) dual-axis
├── RegimeQuadrantChart.tsx      # 20-session scatter with quadrant labels + state-key tiles
├── DivergenceOverlay.tsx        # IV-z (orange) + RV-z (pink) overlay w/ headline σ
└── VrpSpreadPanel.tsx           # Full-width bars + smoothed-line bottom panel
```

All chart components share a small primitive `AnalyticalSeriesPanel.tsx` that enforces the visual language (uppercase mono header, dim subheading, dark `--bg-panel` background, `--border-dim` border, padding). Charts themselves use Recharts (already in the dependency tree from the watchlist work) or a thin SVG-only renderer for the simpler ones.

### 7.3 Colors

Adopt the reference visual language strictly:

| Role | Token | Used by |
|---|---|---|
| Primary accent (teal) | `--accent-bg` | IV, regime dots, headline σ |
| Secondary (purple) | new `--accent-vol` (= same purple as image 18) | IV-of-IV |
| Warm (orange) | new `--accent-warm` (= same orange as image 18/19) | RV, IV-z |
| Vivid pink | new `--accent-vivid` (= same pink as image 18/19) | SPY-corr, RV-z |
| Positive bar | `--positive` | VRP positive bars |
| Negative bar | `--negative` | VRP negative bars |

New CSS variables added to `web/app/globals.css` (the file is already 124KB but tokens additions are still small).

### 7.4 Empty / loading states

- **Backfill running on first request:** API returns 200 with `backfill_status: "running"` and whatever's already in DB. UI overlays "Building 1-year history… (≤30s)" on each empty panel and polls every 5s for up to 60s until `backfill_status === "ready"`.
- **Series too short for derived signals** (e.g., <20 days of IV history → no IV-of-IV, no divergence): the panel renders a "Insufficient history (need ≥20d, have Nd)" message.
- **Missing SPY data** (one-time seed not yet run): RV/SPY-corr panel and Regime Quadrant render a one-line "SPY OHLC not seeded — run scripts/seed_spy_ohlc.py" message instead of crashing.

## 8. Worker / scheduler additions

Adds two jobs to `src/uw_scan/worker/` (existing APScheduler runner):

| Job | Cron | What it does |
|---|---|---|
| `daily_spy_ohlc_refresh` | 16:30 ET weekdays | Pull yesterday + today SPY row via `sources/ohlc.py`; upsert into `index_ohlc_daily`. |
| `nightly_vol_analytics_rollup` | 18:00 ET weekdays | For each watchlist ticker: recompute today's `vrp_daily` + `stock_analytics_daily` rows from latest IV/RV/SPY data. |

Both jobs are additive — no existing job changes. If a job fails the API on-request path still works (it'll backfill on demand).

## 9. Testing

- **Backend unit tests** (`tests/`):
  - `test_vrp_daily_compute.py` — golden-master series math (mean, stdev, z-score) on a synthetic IV/RV input.
  - `test_iv_of_iv.py` — checks 20d window, annualisation factor, behaviour on short series.
  - `test_spy_corr.py` — Pearson correlation on a hand-built series.
  - `test_regime_classifier.py` — all four quadrant boundaries.
  - `test_volatility_series_endpoint.py` — full happy-path integration: seed sample IV/RV/SPY data, hit endpoint, assert shape.
- **Frontend component tests** (`web/tests/`, vitest):
  - Each chart component gets a snapshot test with a fixed input → fixed SVG output.
  - `VolatilityTab.tsx` smoke test: renders all panels in dark mode, no console errors.
- **Manual QA gate:** open the tab on TSLA, AAPL, NVDA, and one low-vol name (PG). All panels render or show explicit empty states. No NaN, no `undefined`, no React `key` warnings.

## 10. Migration

```
1. Add migration 014_volatility_v2_tables.sql with the four new tables.
2. Run `scripts/seed_spy_ohlc.py` once to populate index_ohlc_daily.
3. Deploy backend with new endpoint + worker jobs.
4. Deploy frontend with new VolatilityTab + dropped VrpTab.
```

No data deletion. The old `VRP` URL 404s after step 4 — acceptable.

## 11. Open questions (resolve before implementation)

- **Earnings-marker source.** The HV/IV chart shows blue dots on earnings dates. We have `next_earnings_date` in `BulkScreenerRow`, but not historical earnings dates. Option: pull from FMP or Yahoo earnings calendar one-shot, persist to a new `earnings_history` table. **Defer** — render without markers in v1; add in a follow-up.
- **Smile interpolation.** Some strikes have call-only or put-only IV. Today's plan averages when both are present, falls back to whichever exists. Acceptable for v1; revisit if the chart looks jagged.
- **Per-stock state thresholds.** The regime quadrant uses each stock's own trailing-252d median of `spy_corr_21` as the Y-axis cutoff. For a brand-new ticker this won't be defined. Fall back to 0.5 (a sensible market-wide median) until 252 days of history exists.

---

End of spec.
