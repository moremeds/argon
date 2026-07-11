# Technicals price pane: MarketSmith volume + SMA·σ ⇄ EMA·BB toggle — design

Date: 2026-07-11. Status: approved (brainstorm session).

## Scope

PR A, frontend-only, on the Technicals price pane (`web/components/stock/panels/TechnicalsPriceChart.tsx`, lightweight-charts v5).

Explicitly OUT of scope (separate later PR B): migrating argon's Python
technicals (`cards/technicals.py`) from hand-rolled pandas to TA-Lib to match
apex's `talib.*` usage. That change alters historical RSI/ATR/MACD warmup
values feeding the dual-MACD ALIGN/slope gates and requires
`technicals_refresh_backfill.py` re-runs and gate re-validation — its own spec.

## Decisions (user-confirmed)

1. **Volume (item 1): full MarketSmith port** of the Fred6724 Pine indicator,
   mapped onto the existing volume histogram. **Styling is Argon, not Pine**
   (user directive 2026-07-11): the script's blue/magenta RGB constants are
   dropped; every color comes from the page's CSS variables as resolved by the
   pane's existing `cssVar()` helper — up volume `--positive`, down volume
   `--negative` (both at the existing `59` alpha suffix), low-rel-vol bars and
   labels `--text-muted`, volume-MA line `--accent-warm` family, marker/readout
   text in the existing 10px IBM Plex Mono style. Features ported:
   - color by **previous close** (up `close >= close[1]` → positive, down → negative)
   - **volume MA(50)** line overlaid on the volume scale
   - **low-relative-volume graying**: lowest volume in the trailing 10-bar window → muted gray
   - **low-vol % labels**: belowBar marker `-NN%` when volume ≤ (1 + threshold/100)·MA, threshold −25%
   - **HVE / HV1 labels**: aboveBar marker on the bar with highest volume ever / highest in 252 bars,
     deduped with peak-length 9 (a labeled bar must be the max of ±9 neighbors)
   - **buzz readout**: `VOL 12.3M · 1.4×MA` line appended to the existing hover/last-bar readout
     (DOM overlay, not an lwc table)
   - **2×MA truncation** (MarketSmith display style): OFF by default, no UI toggle in PR A
     (constant in code); hover readout always shows true volume
   - Marginal pieces (HV labels, buzz) ship in PR A and get trimmed after live review if noisy.
2. **Overlay toggle (item 2): two-way mode switch**, small segmented control
   `[ SMA·σ | EMA·BB ]` in the panel header next to the timeframe select:
   - mode `sma` (default): SMA20/50/200 + ±1.5σ band — current behavior, byte-identical
   - mode `ema`: EMA5/EMA20/EMA50 + Bollinger(20, 2·std) band; no basis line
   - persisted per-browser in `localStorage` (same pattern as the tab's reorder persistence)
   - panel title and legend follow the mode
3. **Computation locus: client-side TypeScript over the FULL series.**
   The API's per-bar series comes from persisted JSONB (`fetch_series`), so a
   server-side EMA/BB would require builder+model+persistence+gen:types+backfill+
   two CI dataset gates — rejected for display-only overlays. Instead
   `TechnicalsTab` passes the unwindowed `data.series` to the chart as a new
   `fullRows` prop; EMA/BB/vol-MA/markers are computed over full history and
   then sliced to the visible window, so window left edges are converged
   (EMA50 needs ~150 warmup bars — longer than the 3M window itself) and
   HV1/HVE see pre-window history. Server-side SMAs stay untouched (they feed
   ALIGN/slope gates).

## Architecture

- **NEW `web/lib/indicators.ts`** — pure functions (number[] in/out, null-safe):
  `ema(values, period)`, `sma(values, period)`, `rollingStd(values, period)`,
  plus row-level assemblers producing lwc-ready data over full rows then
  filtered to the window. No React, no chart imports beyond types.
- **`web/lib/priceChartData.ts`** — `toVolumeData` gains prev-close coloring +
  low-vol graying; new `toEmaLineData`, `toBollingerBandData` (reuses
  `BandPoint {time, upper, lower}`), `toVolumeMaData`.
- **`TechnicalsPriceChart.tsx`** — new `fullRows` prop; `mode` state
  (localStorage-backed); reuses the existing 3 LineSeries + BandsIndicator,
  refilled per mode; one new LineSeries for volume-MA on the volume overlay
  scale; v5 `createSeriesMarkers` on the volume series for HV/low-vol labels;
  buzz text appended to the readout div; title/legend per mode.
- **`TechnicalsTab.tsx`** — one line: `fullRows={data.series ?? []}`.
- No backend change, no migration, no `gen:types`, no new dependency.

## Error handling

- Rows with `volume == null` (close-only history) → volume features silently
  absent (existing candleMode gate already covers the histogram).
- `null`/non-finite closes inside windows → indicator emits `null` for that
  bar (whitespace point), never NaN into lwc.
- Band degenerate (std = 0) → skip the point (matches existing `toBandData` z-guard).

## Testing

- Vitest unit tests for `lib/indicators.ts` against a frozen real SPY OHLCV
  fixture (real data captured at authoring time; no runtime network) — EMA/SMA
  cross-checked against independently computed expected values; marker
  selection (HVE/HV1/low-vol) asserted on the fixture.
- Playwright smoke: Technicals tab renders; toggle flips legend labels
  SMA20/50/200 → EMA5/20/50; volume MA line present.
- `npm run typecheck && npm run lint && npm run test` green.

## Rules

- One PR: code + tests + CHANGELOG `[Unreleased]` entry.
- lightweight-charts stays confined to the price pane (documented exception).
