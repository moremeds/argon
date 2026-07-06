# Quant Technicals tab — design

**Date:** 2026-07-06 · **Status:** DRAFT (candidate) · **Effort:** M–L
**Origin:** user idea (sigmoid price model, MA slope/curvature, std of price-change changes), designed out into a full tab.

## What it is

A new `Technicals` tab on `/stock/[ticker]` (fits the existing tab architecture in `web/components/stock/tabs/`), not a standalone page. Enhanced, dimensionless, cross-ticker-comparable takes on RSI/MACD/MA — everything is a z-score or ratio so a reading on NVDA means the same as on KO.

## Data path (no new external plumbing)

- **Bars:** apex `/bars/{ticker}` over Tailscale (`http://100.66.147.98:8322`, verified live 2026-07-06 — daily OHLC deep history, plus baseline `/indicators/{ticker}?indicator=rsi` returning value+zone series). This is the sanctioned price source per the standing apex-REST memory — no direct lake reads.
- **Compute:** new `cards/technicals.py` (pure functions on bar arrays, `Decimal` for prices, numpy for the fits).
- **Persist:** new `technical_daily` table (per the persist-everything rule) — one snapshot row per (ticker, date) with all sub-scores. This is what lets the composite later be marked-out against forward returns in the backtest harness for free.
- **Serve:** `/api/stock/{ticker}/technicals` → typed model → `gen:types`.
- **Refresh:** nightly worker job (`worker/jobs/technical_daily_refresh.py`) over the watchlist; on-demand compute for cache misses at request time.

## The five panels

1. **Sigmoid trend-maturity fit** (core idea). Fit logistic `L/(1+e^(-k(t-t0)))` to the price segment since the last swing pivot. Output: S-curve position `s = k(t_now - t0)` → phase (early / accelerating / decelerating / saturated), steepness `k`, and **R² vs a plain linear fit**. The sigmoid read only counts when it beats linear — otherwise the panel says "no S-curve structure." This guard is what keeps it honest (a sigmoid can fit anything if you don't compare).
2. **MA kinematics.** Slope (velocity) and curvature (acceleration) of EMA20/50/200 via short-window regression, **normalized by ATR(14)** → dimensionless. t-stat of the slope replaces crossover folklore; alignment score across the three EMAs.
3. **Return-distribution panel** (the "std of price-change changes" idea). 20d realized σ z-scored vs its own 252d history; vol-of-vol (std of Δσ); 60d skewness/kurtosis; second-difference std as a "jerkiness" gauge.
4. **RSI enhanced.** RSI(14) z-scored against its own 252d distribution; RSI slope; algorithmic pivot-based divergence detector (price HH + RSI LH, scored by the gap).
5. **MACD enhanced.** Histogram normalized by ATR; its first derivative; cross-sectional percentile across the watchlist.

## Composite

Each panel → one bounded z → a single trend-quality score, with sub-scores always visible (never a black box). Because `technical_daily` snapshots persist, after ~60 sessions the composite graduates from display to a testable signal via the existing walk-forward harness — no extra work to earn that option.

## Build order

1. `cards/technicals.py` + a `demo()` self-check (sigmoid-beats-linear on a synthetic S-curve, flat on noise).
2. `technical_daily` migration + storage repository (standalone, per storage/CLAUDE.md).
3. API model + route + `gen:types`.
4. Nightly worker job.
5. Web tab (hand-rolled SVG, Argon dark theme; reuse existing chart primitives).

## Open items

- apex bar history depth per ticker (saw AAPL back to 2024-07 in the probe — confirm coverage for the full watchlist; short-history names weaken the 252d z-scores).
- Swing-pivot detection algorithm for panel 1's segment start (ATR-based zigzag is the lazy default).
