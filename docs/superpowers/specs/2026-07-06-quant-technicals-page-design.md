# Quant Technicals tab — design

**Date:** 2026-07-06 · **Updated:** 2026-07-08 · **Status:** APPROVED (all 5 original panels + Shepherd elements, additive) · **Effort:** L (2 PRs: backend, web)
**Origin:** user idea (sigmoid price model, MA slope/curvature, std of price-change changes), designed out into a full tab.

## What it is

A new `Technicals` tab on `/stock/[ticker]` (fits the existing tab architecture in `web/components/stock/tabs/`), not a standalone page. Enhanced, dimensionless, cross-ticker-comparable takes on RSI/MACD/MA — everything is a z-score or ratio so a reading on NVDA means the same as on KO.

**Scope decision (2026-07-08):** additive — all five original panels *plus* the Shepherd-screenshot elements (KPI stat-strip, price/MA/σ-band anchor chart, z-vs-200DMA + band labels, annualized-slope regime, the forward-return-by-z-band table, and relative-strength-vs-benchmark). Ships as two PRs (backend, then web) given the size.

## Data path (no new external plumbing)

- **Bars:** apex `/bars/{ticker}?timeframe=1d` over Tailscale (`http://100.66.147.98:8322`, re-verified live 2026-07-08). Response shape: `{symbol, timeframe, bars:[{time, open, high, low, close, volume, vwap}], count}`. apex's per-request cap is being raised to a **2000-bar default** (~8 trading years) by a pending apex-side change (user, 2026-07-08). This is the sanctioned price source per the standing apex-REST memory — no direct lake reads. Also `/indicators/{ticker}?indicator=rsi` for a baseline value+zone series.
  - **Consequence:** ample history for both a live 252d rolling z-score *and* a backfilled historical z-series on any name with the depth. Real coverage still varies by ticker (recent IPOs have less) — surface the sample size behind each z so a thin reading reads as thin. Build defensively: don't hard-assume 2000 rows are present; the higher cap is a pending change, and the compute must degrade gracefully to whatever count apex returns.
- **Compute:** new `cards/technicals.py` (pure functions on bar arrays, `Decimal` for prices, numpy for the fits).
- **Persist:** new `technical_daily` table (per the persist-everything rule) — one snapshot row per (ticker, date) with all sub-scores (including the z-vs-200DMA, band, annualized slope, and composite). This is what lets the composite later be marked-out against forward returns in the backtest harness for free. The **forward-return-by-z-band table** is a per-ticker aggregate, not a daily snapshot — persist it as a JSONB column on the latest snapshot (or a small `technical_forward_returns` sidecar keyed by ticker·band·horizon); recomputed at refresh, cheap to store.
- **Serve:** `/api/stock/{ticker}/technicals` → typed model → `gen:types`. **Deliberately its own endpoint, NOT a field on `SingleStockReport`** — that report is the app's busiest/slowest read path (see `2026-07-06-candidate-stock-page-perf.md`); the sigmoid fits and apex bar-fetch must not bloat it.
- **Render:** client island following the `FrameworkTab`/`TradeInsightsTab` pattern — the tab component takes only `ticker` and fetches `/api/stock/{ticker}/technicals` itself, rather than receiving the server-fetched `report` prop like the `volatility`/`skew`/`flow` tabs do. Integration is two edits:
  - `web/components/stock/TabBar.tsx` — insert `["technicals", "Technicals"]` into `TABS` at **index 1, immediately after `["market-structure", "Market Structure"]`** (order becomes: Market Structure · Technicals · Volatility · Skew · Flow · Trade Insights · Trade Plan).
  - `web/app/stock/[ticker]/[tab]/page.tsx` — add a `if (tab === "technicals") return <TechnicalsTab ticker={ticker} />` branch (alongside the existing `trade-insights`/`trade-plan` client-island branches, so it never touches the `SingleStockReport` fetch).
- **Refresh:** nightly worker job (`worker/jobs/technical_daily_refresh.py`) over the watchlist; on-demand compute for cache misses at request time.

## Reference designs

The "Shepherd Capital Markets" post-market technicals screenshots (user, 2026-07-08) are the visual/feature north star. We adopt their **layout density, KPI stat-strip, regime labels, and the forward-return-by-z-band table**, rendered in the **argon dark theme** (keep argon's dark background + accent; take the terminal-dense monospace layout, not their light background). Their MARKETS-tab sector-breadth / advance-decline views are **out of scope** for a single-stock tab (belongs on `/regime` if ever).

## Layout — header + four sections

**Scope (2026-07-08, user):** additive — all five original panels *plus* the Shepherd elements. Organized into sections so the tall tab stays legible.

### Header — KPI stat-strip

A dense top strip (Shepherd pattern), each tile value + regime label:

- **PRICE** (latest close, as-of date)
- **200 DMA / DISTANCE** (200-day SMA + % distance)
- **Z-SCORE** = price distance from 200 DMA in σ units, labelled (`> 2.0 DEEPLY OVERBOUGHT`, `-1.0 to -0.5 NEUTRAL`, …)
- **200 DMA SLOPE (ann.)** = annualized slope of the 200 DMA, labelled (`WEAK UPTREND` / `STRONG UPTREND` / `DOWNTREND`)
- **Z-SCORE BAND** = which band the current z falls in (drives the forward-return table highlight)

### Anchor chart

**PRICE, MOVING AVERAGES & ±1.5σ BAND** — close + SMA20/50/200 + a ±1.5σ envelope around the 200 DMA. The tab's primary chart.

### Section A — Trend & position

1. **Z-vs-200DMA** — the headline z (price distance from 200 DMA in σ), with the **Z-SCORE VS 200 DMA** history chart (the banded time series) and current band label.
2. **MA kinematics** — SMA/EMA20/50/200 slope (velocity) and curvature (acceleration) via short-window regression, **normalized by ATR(14)** → dimensionless; t-stat of the slope replaces crossover folklore; three-MA alignment score. Includes the **SMA SLOPE (% per day)** chart and the annualized 200 DMA slope regime label (Shepherd framing).
3. **Sigmoid trend-maturity fit** (our original core). Fit logistic `L/(1+e^(-k(t-t0)))` to the price segment since the last swing pivot (ATR-zigzag). Output: S-curve position `s = k(t_now - t0)` → phase (early / accelerating / decelerating / saturated), steepness `k`, and **R² vs a plain linear fit**. Only counts when it beats linear — otherwise "no S-curve structure." The beats-linear guard keeps it honest.

### Section B — The signal (⭐ the standout)

4. **Forward-return by z-score band** — Shepherd's killer table, per ticker. Over the ~2000 available sessions, assign each historical session its z-vs-200DMA band, then compute the **N-day forward return** (headline N = 40d, code parameterized for 20/40/60). Bucket by band → **count · mean return · median return · win-rate**, with the current band's row highlighted. Turns the z-score from description into a conditional bet. **Look-ahead discipline:** bands are defined ex-ante from data available at each session; forward returns use only future bars. This is backtest-adjacent math — persist the full table (per the persist-everything rule) and record the reproduce path.

### Section C — Distribution & oscillators

5. **Return-distribution** (the "std of price-change changes" idea). 20d realized σ z-scored vs its own 252d history; vol-of-vol (std of Δσ); 60d skewness/kurtosis; second-difference std as a "jerkiness" gauge.
6. **RSI enhanced.** RSI(14) z-scored against its own 252d distribution; RSI slope; algorithmic pivot-based divergence detector (price HH + RSI LH, scored by the gap).
7. **MACD enhanced.** Histogram normalized by ATR (Shepherd shows MACD 8/17/9); its first derivative; cross-sectional percentile across the watchlist.

### Section D — Relative strength

8. **Relative strength vs benchmark** — Shepherd's RS-ratio panel, single-stock flavour: `TICKER / SPY` ratio + its 60/200-day MAs, answering "is this name out/under-performing its benchmark and is that trend turning." v1 = SPY only; sector-ETF benchmark (needs a ticker→sector map) is a deferred nice-to-have.

## Composite

Each panel → one bounded z → a single trend-quality score, with sub-scores always visible (never a black box). Two independent paths make the composite testable in the walk-forward harness: (a) with the ~2000-bar apex depth we can compute a **historical** `technical_daily` series retroactively, and (b) `technical_daily` snapshots persist **nightly** so we also bank forward-looking history. Either way the composite graduates from display to signal with no extra plumbing. The Section-B forward-return-by-z-band table is the inline, per-ticker preview of exactly that graduation — it's the same conditioning the harness would do, shown live.

## Build order

Given 8 panels + header + anchor chart, this is a **large diff — recommend two PRs** at the backend/web seam (the tab is inert without the endpoint, so no half-shipped state):

**PR 1 — backend**
1. `cards/technicals.py` — pure functions for every panel + `demo()` self-checks: sigmoid-beats-linear on a synthetic S-curve (flat on noise); z-vs-200DMA and band assignment on a known series; forward-return-by-band bucketing on a fixture with a hand-verified row (this is the money path — it gets an explicit assert).
2. `technical_daily` migration + forward-return storage (JSONB column or `technical_forward_returns` sidecar) + standalone storage repository (per storage/CLAUDE.md).
3. API model + `/api/stock/{ticker}/technicals` route + `gen:types`.
4. Nightly `worker/jobs/technical_daily_refresh.py` over the watchlist; on-demand compute for cache misses.

**PR 2 — web**
5. `TechnicalsTab` client island + KPI stat-strip + anchor chart + the four sections (hand-rolled SVG, argon dark theme; reuse existing chart primitives). Wire `TabBar.tsx` + `[tab]/page.tsx`.

## Resolved items (2026-07-08)

- **apex bar depth** — RESOLVED. Default being raised to ~2000 daily bars (~8yr) by a pending apex-side change (user). Ample for live 252d z-scores and a retroactive historical series. Compute must degrade to whatever count apex actually returns (don't assume 2000) and surface the sample size (`n` bars behind each z) so a thin reading is visibly thin rather than silently wrong.
- **Swing-pivot detection** (panel 1 segment start) — RESOLVED: ATR-based zigzag (standard default). Pivot = a high/low that reverses by ≥ k·ATR(14); segment start = the most recent confirmed pivot.
- **Render/perf boundary** — RESOLVED: own endpoint + client island, off the `SingleStockReport` hot path (see Data path).

## Ceilings (ponytail)

- ~2000 apex bars is the data ceiling; if the composite ever needs history beyond that, the upgrade path is a lake read, not part of v1.
- Sigmoid fit uses `scipy.optimize.curve_fit` (scipy 1.18.0 confirmed installed 2026-07-08) with the beats-linear R² guard; no bespoke optimizer.
