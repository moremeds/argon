# Dual MACD + Live Technicals Coverage — Design

**Date:** 2026-07-09 (converged 2026-07-10)
**Status:** Approved (brainstorm), pending implementation plan
**Related:** `docs/superpowers/specs/2026-07-06-quant-technicals-page-design.md` (Quant Technicals tab), `worker/jobs/regime_live.py` + `scanners/live_quotes.py` (the live splice pattern this reuses)

## Summary

Three coupled changes to the Quant Technicals tab, all on the **daily** timeframe:

1. **Replace the single MACD histogram with a dual MACD** — apex's slow (55/89/34) + fast (13/21/9) pair, ATR-normalized, rendered as a contrasting long-period / short-period histogram with the full state machine (trend_state, tactical_signal, momentum_balance, confidence).
2. **Live coverage for all technicals** — a scheduler job splices today's live spot onto each ticker's stored daily history as the forming daily close and recomputes the fast-moving metrics, so every daily chart's *latest* reading updates intraday instead of being frozen at last night's close.
3. **Extend history to 5 years** — the same depth for every technicals series (not just dual MACD).

### Decisions locked during brainstorm

- **Dual MACD params + scale:** apex periods (55/89/34 slow, 13/21/9 fast), **ATR(14)-normalized** to argon house style so both histograms sit on one comparable ~[-2,+2] scale.
- **State depth:** full apex state machine (trend_state, tactical_signal DIP_BUY/RALLY_SELL, momentum_balance, confidence).
- **Dual MACD is ported into argon**, not fetched from apex. (apex *does* expose it at `GET /indicators/{ticker}?indicator=dual_macd`, but see "Why not apex for live" below.)
- **Live coverage is argon-side**, using argon's own **xenon WS `intraday_quote`** feed as the live-price source (the only confirmed-live source).
- **Charts stay daily.** No 5m intraday chart — see "Why not apex for live."
- **Delivery:** scheduler-cached (job writes a cache table; the page polls a cheap read).

### Why not apex for live coverage (investigation result, 2026-07-10)

apex's REST `/indicators` / `/bars` are compute-on-read off the **livewire bronze parquet lake** (`LivewireOhlcProvider`). livewire refreshes its intraday bronze via a **once-daily catchup job at 05:00 UTC** (`com.livewire.intraday-catchup`, single-shot, delegating to `daily-backfill`) — it backfills the *prior* session overnight. So during RTH, apex's newest 5m bar is yesterday's; apex REST cannot supply a live intraday price. (livewire *does* warehouse 5 years of 5m history — deep, just not fresh intraday.) apex's only live surface is its WS *signal* stream (fired signals, wrong shape for charting). argon's xenon IB WS feed (`intraday_quote`, 24h while IB connected, already used by `regime_live`) is the correct live source. apex remains the **nightly daily-bar** source, unchanged.

Non-goals: intraday *bar* charts, live sigmoid / forward-returns, non-watchlist tickers, changes to the composite score or forward-return calibration.

---

## Part 1 — Dual MACD (daily, replaces single MACD)

Port the math/state from apex `src/domain/signals/indicators/momentum/dual_macd.py` (`_calc_macd_*`, `_rolling_pctile_rank`, `_get_state`) — not apex's `IndicatorBase` plumbing — and normalize by ATR(14) instead of apex's raw ×2 multiplier.

### Compute — `cards/technicals.py` (pure functions, no I/O)

**`dual_macd_series(df) -> pd.DataFrame`** — per-session, all ATR(14)-normalized:

| column | meaning |
|---|---|
| `fast_macd_hist_atr` | MACD(13,21,9) histogram / ATR(14) |
| `slow_macd_hist_atr` | MACD(55,89,34) histogram / ATR(14) |
| `fast_macd_delta` | slope of fast hist over `slope_lookback=3` |
| `fast_macd_delta2` | second difference of `fast_macd_delta` (curvature → confidence) |
| `slow_macd_delta` | slope of slow hist over `slope_lookback=3` |
| `fast_macd_norm` | 252d causal percentile-rank of `abs(fast_macd_hist_atr)` |
| `slow_macd_norm` | 252d causal percentile-rank of `abs(slow_macd_hist_atr)` |

MACD via the existing `close.ewm(span=…)` approach (no TA-Lib). Percentile-rank ports apex `_rolling_pctile_rank` (causal, 0–1).

**`dual_macd_state(last_row) -> dict`** — port of apex `_get_state` on the ATR-normalized histograms:

- `trend_state` (override-first): `slow>0 & slope<0 → DETERIORATING`; `slow<0 & slope>0 → IMPROVING`; else `BULLISH`/`BEARISH` on sign of slow.
- `tactical_signal`: `DIP_BUY` when `slow>0 & fast<0 & |Δfast|>|Δslow| & Δfast≥0`; `RALLY_SELL` mirror; else `NONE`.
- `momentum_balance`: freeze-zone `BALANCED` when both norms < 0.15; else `FAST_DOMINANT`/`SLOW_DOMINANT` on the 1.5× rule; else `BALANCED` (uses `fast/slow_macd_norm`).
- `confidence` (0–1): `clip(fast_delta2 / max(|fast_hist|, eps), 0, 1)` for DIP_BUY, negated for RALLY_SELL; `0.0` when no tactical signal.

### Persistence — no schema migration

- The seven `dual_macd_series` columns append to the existing `metrics` JSONB blob (extend `_METRIC_COLS` in `storage/technicals_repository.py`). JSONB is schema-flexible → no SQL migration.
- The `dual_macd_state` dict is stored under `detail.dual_macd` (extend the detail assembled in `worker/jobs/technical_daily_refresh.py`).
- **Unchanged:** top-level `macd_hist_atr` column, `macd_enhanced`, `macd_slope3`, `composite_score`, `forward_return_table`. No recalibration; the old single histogram just stops being charted.

### API contract

- Extend the technicals response model so the new `metrics` series columns and `detail.dual_macd` surface. Add fields **surgically** (alphabetical slot) per the generated-files rule; run `gen:types`, commit the `web/lib/types.ts` diff, update the OpenAPI snapshot in the same PR.

### Viz — `web/components/stock/panels/TechnicalsOscillators.tsx` (`TechnicalsMacdChart`)

- Two overlaid histograms with deliberate contrast: **slow (long-period)** as a muted, wider filled histogram behind; **fast (short-period)** as a sharp foreground histogram — "tactical timing inside structural trend." Because both are ATR-normalized they share the y-axis; if amplitudes still diverge, scale each to comparable range for the overlay (viz-only).
- Headline badge: `tactical_signal` (`DIP_BUY · conf 0.72`), colored `--positive`/`--negative`/muted for NONE. Subtitle: `trend_state · momentum_balance`.
- Title `Dual MACD — 13/21/9 vs 55/89/34`, subtitle `ATR-normalized`. Reuse `OscillatorChart`; add a second `histogram` overlay prop (fast `--accent-vivid`, slow dim `--accent-vol`/`--text-muted`). Update the explanation prose to describe the dual-timeframe read + DIP_BUY/RALLY_SELL logic.

---

## Part 2 — Live coverage (all daily technicals)

Reuses `regime_live` + `load_live_quotes`: load the freshest WS quote, splice it as today's provisional daily close onto the stored daily history, re-run the pure derivers.

### Recompute scope — fast-moving subset only

Per live tick, recompute only what a single provisional close changes: `z_vs_200dma` + `z_band`, `rsi14` + `rsi_z`, **dual MACD state + last fast/slow histogram point**, `rv20`, MA-kinematics slopes (`kin_slope20/50/200`), `composite`. **Carried from the nightly `detail`** (static intraday): `sigmoid`, `forward_returns`, `rs`. Rationale: the sigmoid runs a scipy `curve_fit` and forward-returns are historical conditioning — neither moves from today's spot, and ~100 curve_fits every 5 min is wasted CPU.

### Shared deriver (module budget)

Extract the fast-moving math into one helper `live_technical_snapshot(df, spot) -> dict` in `cards/technicals.py`: append `spot` as the final provisional close, compute the subset via the *same* functions the nightly path uses (no copy-paste of z/RSI/MACD math). Both the live job and (optionally) the nightly snapshot call it.

### Job — `worker/jobs/technical_live.py` + `scheduler.py`

- `technical_live_scan(repo, settings, ticker_filter=None)`: for each watchlist ticker, load stored daily closes + latest `intraday_quote`; stale (`> max_age`) or missing quote → skip; else `live_technical_snapshot` → upsert cache row.
- Registered in `scheduler.py` at `*/5` min during market hours (ET), gated by `TECHNICAL_LIVE_ENABLED` (default **false** until deployed). Per-outcome counters (`ok`/`skipped_stale`/`failed`); `logging` per module convention.
- Zero external calls — the WS consumer already writes `intraday_quote`; the daily history is already in `technical_daily`.

### Storage — new latest-only cache table

Migration `103_technical_live.sql`:

```sql
CREATE TABLE IF NOT EXISTS technical_live (
    ticker       text PRIMARY KEY,
    captured_at  timestamptz NOT NULL,
    spot         double precision,
    spot_source  text,
    payload      jsonb NOT NULL,
    inserted_at  timestamptz NOT NULL DEFAULT now()
);
```

Latest-only (upsert on `ticker`, no `(ticker, as_of)` history) → **does not trip `test_data_gap_full_coverage`** (no DatasetRegistryEntry) and is not a temporal warm-store table. Canonical history stays in `technical_daily`. Freshness monitoring on `captured_at` deferred. New standalone `TechnicalLiveRepository` (`storage/technical_live_repository.py`) — `upsert(...)` + `fetch(ticker)`; not appended to `repository.py` (repository-split rule).

### API — `GET /api/technicals/{ticker}/live`

Reads the cache row (cheap). Returns `{captured_at, spot, spot_source, z, z_band, rsi14, rsi_z, dual_macd, rv20, kinematics, composite}` or `null` when no fresh row. Typed model in `models/technicals.py`, re-exported from `models/__init__.py`.

### Frontend — Technicals tab polling

- The tab (client component) polls `/live` every ~20–30s. On a fresh row: overlay live values onto the server-rendered daily baseline — update the last dual-MACD histogram bar and refresh the z / RSI / composite headlines and the live `tactical_signal` badge.
- Live badge: `LIVE · HH:MM:SS · <spot_source>` (green fresh, grey/"EOD" when stale or absent). Server-rendered daily payload stays the baseline when live is unavailable.

---

## Part 3 — History extension to 5 years

Currently the technicals series stores ~504 sessions (~2yr; `fetch_series` `limit=504`) and the nightly builds from whatever depth `fetch_daily_bars` pulls.

- **All technicals series** extend to ~5 years (~1260 sessions). apex `/bars` supports full history (`limit<=0`); livewire warehouses ≥5yr of daily bars.
- Bump the nightly daily-bar fetch depth and `fetch_series` limit (~1260). Warmups are safe within 5yr (200 SMA, 252d z-window, dual MACD 55/89 + 252 norm ≈ 341 bars).
- One-time deepening happens on the next nightly `technical_daily_refresh` after deploy (idempotent upsert); no separate backfill script needed. Note the larger per-ticker payload/row count in the PR.

---

## Testing

- **Unit** (`tests/unit/`): `dual_macd_series` column shapes + frozen-fixture value check on a real ticker's real daily bars (no-synthetic-data rule); `dual_macd_state` truth table (every trend_state / tactical_signal / momentum_balance branch); `confidence` bounds; `live_technical_snapshot` splice correctness (last close == spot, subset keys present, sigmoid/fwd absent).
- **Integration** (`tests/integration/`, pytest-postgresql): `upsert_series` round-trips the new `metrics` keys; `technical_live` upsert/fetch; `technical_live_scan` end-to-end with a seeded `intraday_quote` + `technical_daily` history → cache row written; stale quote → skipped.
- **Smoke (real worker path):** enable flag → worker runs `technical_live_scan` → `technical_live` row → tab renders the live head/badge. Restart the worker stack first (APScheduler doesn't hot-reload).
- **Web:** vitest for the dual-histogram panel + live-badge stale/fresh states; `gen:types` diff committed.

## Rollout

- `TECHNICAL_LIVE_ENABLED=false` on merge; flip on the mini after deploy + worker restart (env frozen at fork). Requires `XENON_WS_ENABLED=true` on the mini for live quotes; otherwise the tab shows EOD (graceful).
- Dual MACD series + 5yr depth populate on the next nightly `technical_daily_refresh`. Live rows populate on the first scan after enable.
- CHANGELOG `[Unreleased]` entry rides this PR.

## Open items (deferred, not blocking)

- Live `rs` (SPY ratio) recompute — carried from nightly in v1.
- Freshness monitor keyed on `technical_live.captured_at`.
- Intraday-bar (5m) dual MACD — infeasible today (livewire intraday bronze is refreshed nightly, not live). Revisit only if a live intraday-bar source appears.
