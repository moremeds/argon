# Technicals price pane → lightweight-charts (candles, volume overlay, anchored VWAP)

**Date:** 2026-07-10
**Issue:** [#256](https://github.com/moremeds/argon/issues/256) (scoped down — price pane only)
**Status:** design approved, pending spec review

## Summary

Replace the hand-rolled SVG **price/anchor pane** on the `/stock/[ticker]` Technicals
tab with a [`lightweight-charts`](https://github.com/tradingview/lightweight-charts)
(v5.2, Apache-2.0, ~45 KB canvas) chart, and use the migration to add three features
that static SVG can't give cheaply:

1. **Candlesticks** (O/H/L/C) instead of a close line.
2. **Volume overlay** in the price pane (bottom band).
3. **Click-to-anchor VWAP** — click a bar, get a VWAP line computed from that bar
   forward; the anchor + computed series persist in Postgres.

Everything else on the tab — dual-MACD, Z-score, RSI, RV, MA-kinematics, RS,
forward-return table, KPI strip, detail panels — **stays exactly as it is** (SVG,
untouched). This is the smallest change that delivers the candlestick view.

## Why this overrides a convention (and it's deliberate)

`web/CLAUDE.md` and `web/components/CLAUDE.md` both say *"No charting library.
Don't pull in recharts/d3/visx."* This PR consciously overrides that **for
`lightweight-charts` only** — a tiny imperative canvas lib, not a React chart
framework. Both CLAUDE.md files get an explicit documented exception in the same PR.

Considered and rejected: keeping the price pane as SVG. Candlesticks are only legible
when zoomed, and lightweight-charts brings drag-to-pan, scroll-to-zoom, price-scale
autoscaling, a polished crosshair+tooltip, and a battle-tested renderer for 1000+
bars — all of which SVG would have to reimplement. For a candlestick view the library
earns its keep. (For a plain crosshair on the *existing* line chart, SVG would have
been lazier — but that is not the chosen scope.)

## Data layer — persist the OHLCV that's already fetched

**Key fact:** `worker/jobs/technical_daily_refresh.py` already calls
`sources.apex.fetch_daily_bars(t)`, and `cards/technicals.build_technical_series`
already builds a frame with columns `["as_of","open","high","low","close","volume"]`.
The full OHLCV is in hand every night — only `close` is persisted today. So this is a
carry-through, not a new fetch.

### Migration `105_technical_daily_ohlcv.sql`
```sql
BEGIN;
ALTER TABLE uw_scan.technical_daily
  ADD COLUMN IF NOT EXISTS open   DOUBLE PRECISION,
  ADD COLUMN IF NOT EXISTS high   DOUBLE PRECISION,
  ADD COLUMN IF NOT EXISTS low    DOUBLE PRECISION,
  ADD COLUMN IF NOT EXISTS volume BIGINT;
COMMIT;
```

### Write path
- `storage/technicals_repository.py` — add `open/high/low/volume` to the INSERT column
  list, the `%(...)s` params, the `ON CONFLICT DO UPDATE` set-list, and the series
  SELECT.
- `cards/technicals.build_technical_series` — carry the four columns onto each emitted
  series row (they're already in the dataframe).

### Read path / contract
- `models/technicals.py` — add `open/high/low/volume` (`float | None` for
  O/H/L, `int | None` for volume) to the series-row model.
- `reports/technicals.py` — pass them through.
- `web`: `npm run gen:types` to regenerate `lib/types.ts`.

### Backfill — none needed (OHLCV rides the existing full-recompute)
`technical_daily_refresh` **full-recomputes the entire 5Y series from apex bars and
`upsert_series`-writes every row** every run (job docstring line 1; not incremental).
So once the write path carries OHLCV, history fills automatically:
- **Nightly bulk:** the next scheduled `technical_daily_refresh` fills OHLCV for every
  watchlist ticker's whole history — no separate step.
- **Per-ticker on-demand:** the existing `POST /stock/{ticker}/technicals/refresh`
  (which calls `technical_daily_refresh(ticker_filter=[t])`) rewrites one ticker's full
  history immediately.

`scripts/backfill/technicals_refresh_backfill.py` remains available as a manual
"kick it now for everyone" convenience, but is not required.

### Transition-gap UX (chosen: auto-fill on page open)
Between deploy and a ticker's next refresh, its old rows have null OHLCV. The price
pane handles this without a broken state:
- **Graceful degrade:** null OHLCV → render a **close line** (today's exact look);
  present OHLCV → render candles + volume. VWAP anchoring is enabled only when OHLCV
  is present (it needs H/L/C/volume).
- **Auto-fill once:** when the latest series row lacks OHLCV, the tab fires the existing
  per-ticker refresh (`api.technicalsRefresh(ticker)`) a single time on open, then
  re-fetches. Self-limiting — once OHLCV is filled the condition is false, so it never
  re-fires on later visits. Guard against a refetch loop (only auto-fill if
  `latest.open == null` AND we haven't already triggered this mount).

### Data-gap / freshness
Same table, same `(ticker, as_of)` grain, same nightly writer — no new
DatasetRegistryEntry needed (the table is already registered; we only widen columns).

## Anchored VWAP — persist anchor + snapshot, one per ticker

### Migration `106_technical_vwap_anchor.sql`
```sql
BEGIN;
CREATE TABLE IF NOT EXISTS uw_scan.technical_vwap_anchor (
  ticker        TEXT PRIMARY KEY,
  anchor_date   DATE NOT NULL,
  vwap_snapshot JSONB NOT NULL,          -- [{as_of, vwap}] from anchor forward
  computed_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
COMMIT;
```

### Compute (server-side, authoritative)
Anchored VWAP over the persisted OHLCV: for bars `i >= anchor`,
`typical_i = (high_i + low_i + close_i) / 3`, and
`vwap_i = Σ_{k=anchor..i}(typical_k · volume_k) / Σ_{k=anchor..i}(volume_k)`.
float math (matches `cards/technicals.py`'s stated float-only convention; chart-grade
series, not money math). Bars with null volume are skipped in
the cumulative sums (carry the prior VWAP forward). New function in
`cards/technicals.py` (`anchored_vwap(series, anchor_date) -> list[VwapPoint]`), pure
and unit-testable.

### Storage
`storage/technical_vwap_anchor_repository.py` (its own module — not appended to
`repository.py`, per the split rule): `upsert(ticker, anchor_date, snapshot)`,
`get(ticker)`, `delete(ticker)`.

### API (sanctioned writes on the read-only stock router)
Precedent: the existing `POST /stock/{ticker}/technicals/refresh` is already the one
deliberate write on the read-only stock router. Mirror it:
- `POST /api/stock/{ticker}/vwap-anchor` body `{anchor_date: "YYYY-MM-DD"}` →
  server recomputes VWAP from `technical_daily` OHLCV, upserts anchor + snapshot,
  returns `{anchor_date, series:[{as_of, vwap}]}`. Validates `anchor_date` is a real
  bar in range (400 otherwise).
- `DELETE /api/stock/{ticker}/vwap-anchor` → clears the row (204).
- The persisted anchor is delivered to the page by adding a `vwap_anchor` field to the
  technicals GET response (`{anchor_date, series} | null`), so a reload restores the
  drawn line without a second round-trip.

The VWAP request/response models go in `models/technicals.py` (they're a technicals
contract, re-exported from `models/__init__.py`); run `gen:types` after.

## Frontend — new price pane component

New client component `web/components/stock/panels/TechnicalsPriceChart.tsx` replaces
`TechnicalsAnchorChart` in `TechnicalsTab.tsx`. Imperative lightweight-charts wrapped
in `useEffect` + a `ref`; created once per mount, updated via `series.setData` on data
change (not re-created), disposed on unmount (`chart.remove()`), and
`ResizeObserver`-driven width.

### Series (v5 `chart.addSeries(SeriesType, opts)` API)
- **CandlestickSeries** — O/H/L/C; up `--positive`, down `--negative`.
- **HistogramSeries** volume overlay — `priceScaleId: ''`,
  `scaleMargins {top: 0.7, bottom: 0}`, `priceFormat.type: 'volume'`.
- **LineSeries ×3** — SMA20 `--accent-warm`, SMA50 `--accent-vol`, SMA200
  `--accent-vivid`.
- **±1.5σ band** — recovered from stored `z` exactly as today
  (`half = 1.5·(close−sma200)/z`), rendered as a filled envelope via the official
  `bands-indicator` **primitive plugin** (`series.attachPrimitive(...)`), vendored
  into `web/lib/lwc/bandsIndicator.ts`. Preserves the current filled look.
- **VWAP LineSeries** — drawn from the persisted/recomputed anchor snapshot; hidden
  when no anchor.

### Interaction
- **Anchor a VWAP:** `chart.subscribeClick(param => param.time)` → resolve the clicked
  bar's date → compute VWAP locally for instant redraw → `POST /vwap-anchor` to
  persist (server snapshot is the record of truth; reconcile on response).
- **Re-anchor:** clicking another bar replaces the anchor (upsert).
- **Clear:** a small `VWAP from YYYY-MM-DD ✕` chip in the panel header →
  `DELETE /vwap-anchor` + hide the series.
- **Crosshair + tooltip:** built-in; theme the crosshair to `--text-muted`. A hover
  readout (date + OHLC + volume) via `subscribeCrosshairMove` into a small DOM overlay.

### Theming (argon dark)
`createChart` options: `layout.background {type: solid, color: 'transparent'}`,
`layout.textColor` = `--text-muted`, `grid.vertLines/horzLines.color` =
`--border-dim`, `timeScale.borderColor`/`rightPriceScale.borderColor` = `--border-dim`,
`crosshair` mode Normal. CSS-variable colors resolved via
`getComputedStyle(document.documentElement).getPropertyValue(...)` at mount (canvas
needs concrete colors, not `var(--…)`).

### Timeframe selector
The existing `TimeframeSelect` (full/1y/ytd/3m) still lives in the price pane header.
On timeframe change, re-`setData` the windowed OHLCV and call
`timeScale().fitContent()`. (lightweight-charts also allows native zoom/pan on top.)

## Accepted tradeoffs

1. **Horizontal alignment:** the lightweight-charts price pane lays out its own x-axis
   and will **not** be pixel-column-aligned with the 5 SVG oscillator panes below (which
   share `CW/xScaleFor`). Decision: **build it and evaluate visually**, iterate on
   margins if it reads badly. Not a blocker.
2. **Dual-MACD unchanged:** stays SVG with its narrow-fast/wide-slow bar-width encoding
   intact (explicitly out of scope now).

## Out of scope

- Migrating any oscillator pane.
- Syncing the lightweight-charts crosshair into the SVG panes.
- Multiple simultaneous VWAP anchors per ticker (one anchor per ticker; revisit if
  needed).
- OHLC candles for indices/thin tickers with no apex bars (they keep whatever the
  refresh produced; candle series simply renders the bars present).

## Testing / verification

- **Python unit:** `anchored_vwap` on a small frozen real-ticker OHLCV fixture
  (assert cumulative math + null-volume skip). Repository upsert/get/delete round-trip
  (pytest-postgresql).
- **API:** POST/GET/DELETE `/vwap-anchor` integration test; technicals GET now returns
  `open/high/low/volume` + `vwap_anchor`.
- **web unit (vitest):** local VWAP compute matches server; timeframe windowing of
  OHLCV.
- **Smoke (real worker path):** migrate → open `/stock/<ticker>` Technicals tab (old
  rows show a close line, auto-fill fires, page re-fetches → candles + volume render) →
  click a bar → VWAP line draws and survives reload → clear removes it. Confirm a
  second visit does **not** re-fire the auto-fill. User validates via the web page.

## Files touched

| Layer | File |
|---|---|
| migration | `storage/migrations/105_technical_daily_ohlcv.sql`, `106_technical_vwap_anchor.sql` |
| compute | `cards/technicals.py` (carry OHLCV; `anchored_vwap`) |
| storage | `storage/technicals_repository.py` (OHLCV cols); `storage/technical_vwap_anchor_repository.py` (new) |
| model | `models/technicals.py` (OHLCV fields; VWAP models) |
| report | `reports/technicals.py` (pass-through; attach `vwap_anchor`) |
| api | `api/routers/stock.py` (POST/DELETE `/vwap-anchor`); `api/routers/ohlc.py` unchanged |
| worker | `worker/jobs/technical_daily_refresh.py` (verify OHLCV persisted) |
| web dep | `web/package.json` (+`lightweight-charts`) |
| web | `components/stock/panels/TechnicalsPriceChart.tsx` (new, replaces `TechnicalsAnchorChart`); `lib/lwc/bandsIndicator.ts` (vendored); `components/stock/tabs/TechnicalsTab.tsx` (swap); `lib/api.ts` (vwap-anchor calls); `lib/types.ts` (regen) |
| docs | `web/CLAUDE.md`, `web/components/CLAUDE.md` (documented library exception); `CHANGELOG.md` `[Unreleased]` |

`TechnicalsAnchorChart.tsx` is retired once the swap lands; `OscillatorChart` /
`ChartDateAxis` stay (still used by the SVG oscillators).
