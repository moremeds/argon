# Changelog

All notable changes to Argon are documented here. Format loosely based on
[Keep a Changelog](https://keepachangelog.com/) with semver versioning.
`VERSION` is the source of truth; `pyproject.toml` and `web/package.json`
version in lockstep (enforced by `scripts/release/version_sync_check.py`).

## [Unreleased]

### Fixed

- **Runtime assets now ship inside the Python package.** `docker/app.Dockerfile`
  never copied `docs/`, so `canary-calibration-v1.json` and `guidance.md`
  vanished in the container after the 2026-07-08 Docker cutover: every canary
  run raised `FileNotFoundError` and `GET /api/regime/guidance` returned HTTP
  500 for 12 days. Both files moved to `uw_scan.cards.data` and are loaded via
  `importlib.resources`, with a `[tool.setuptools.package-data]` declaration so
  they also ship in release wheels.
- **`GET /api/regime/guidance` no longer degrades to an empty rule list** when
  `guidance.md` cannot be read — a missing runtime asset is now a loud failure.
- **A missing parquet-lake root now raises instead of returning `[]`.** The
  containers had no lake mount, so `resolve_lake_root` fell through to a
  Cloudflare R2 bucket whose producer died 2026-05-21. `vol_index_lake_sync`
  read the frozen bucket, inserted nothing, and logged nothing — freezing
  `vol_index_daily` and all EOD CRI/VCG/canary snapshots at 2026-07-07 for 13
  days while `basis='live'` rows stayed current and masked it. A mounted-but-
  empty lake now raises too.
- **`docker-compose.yml` mounts the lake** at `/lake` (the real
  `/Volumes/DATA_LAKE/...` path — `~/market-warehouse/data-lake` is a symlink
  and colima does not mount `$HOME`), parameterized via `ARGON_LAKE_HOST_PATH`.
- **The worker refuses to boot when retired R2 settings are present**, so a
  stale bucket can never silently take over again.
- **`vrp_macro_drawdown` reads its lake root from `Settings`** instead of a bare
  `os.environ` lookup with a home-dir fallback, consolidating path defaults into
  `config.py`.

### Added

- `scripts/check_runtime_assets.py` CI guard: no `Path.home()` outside
  `config.py`, no runtime `docs/` path construction in `src/`, and no named
  runtime asset reached through a `docs/` path in `src/` or the image-shipped
  `scripts/`.
- `scripts/smoke_container_assets.sh`: verifies the built image can load both
  runtime assets — the only check that reproduces the cutover failure.

### Changed

- `REGIME_RECOVERY_LOOKBACK_DAYS` 7 → 30 (calendar days). A recovery window must
  exceed time-to-detect, not typical outage length.

## [0.10.10] — 2026-07-20


### Added

- Volume profile on the Technicals price chart, behind a `VP` toggle beside
  `Zen` (localStorage-persisted, candle-mode only). Renders against the right
  edge of the price pane: horizontal bars per price bin, buy volume (bars that
  closed up) hugging the axis and sell volume stacked outside, length scaled to
  the busiest bin. Value-area bins (70%) draw at full opacity, tails dim; an
  amber line marks the POC. Binning math is pure and unit-tested
  (`web/lib/volumeProfile.ts` — volume conservation, contiguous bins, minimal
  value area, determinism, against the frozen real SPY OHLCV fixture); painting
  is a lightweight-charts series primitive (`web/lib/lwc/volumeProfile.ts`) in
  the mold of `chanlunZhongshu.ts`, drawn in the **background** layer so it
  never buries the newest candles. Each bar spreads its volume evenly across its
  own high–low (daily OHLCV is all we have) — where-it-traded context, not an
  order book, and explicitly not a signal.
- **Fixed 360-session profile window**, not the visible range. Shipped as VRVP
  first and that was wrong: panning between ~150 and ~600 visible bars moved the
  POC by a median of **11.6 ATR** across six names, so the levels were largely a
  function of the viewport. The window is now counted back from the newest bar
  and fed from the unwindowed series, so pan, zoom and the 3M/1Y/FULL selector
  all leave the levels untouched. 360 is measured, not inherited: stability keeps
  improving out to 5 years, but by then the POC sits 35–92% below spot — steady
  because it describes a market that no longer exists. Study:
  `docs/research/2026-07-20-volume-profile-window-study.md`, reproduce with
  `npx tsx scripts/research/volume_profile_window_study.mts`.
- Volume-profile S/R matrix on the same `VP` toggle: high-volume nodes become
  support/resistance bands (greedy peak-picking with proportional separation,
  per-side caps and a strength floor), labelled with strength as a % of the POC
  and a distinct-retest count; low-volume nodes render as labelled
  (`LVN <price>`) long-dashed lines, styled to read distinctly from the chart's
  own dotted grid rather than as furniture. A
  stats readout (`VolumeProfileStatsPanel`) shows POC/VAH/VAL, nearest S/R with
  zone counts, and value-area bias; its numbers are pushed up from the chart
  primitive rather than recomputed, so they always describe the bars actually
  binned. Zones are descriptive only — the same study found **no forward-return
  edge on either side** (resistance correct in 2–3 of 6 names at every window
  tested; support's apparent edge did not survive a distance-matched placebo).

- Fair value gaps behind a separate `FVG` toggle (default off): unfilled
  three-bar imbalances drawn as amber boxes extending to the right edge, via
  `web/lib/fvg.ts` (O(n) back-to-front fill test). Deliberately stricter than
  the Pine original — a gap closes as soon as any later bar _enters_ the band,
  not only when price traverses it completely, since a partially-traded band is
  no longer untraded. Painting reuses the existing zhongshu rectangle primitive
  rather than cloning it.
- The fast pair's own MACD and signal lines in the dual-MACD sub-pane, drawn
  over its histogram on the same ATR-normalized scale (the histogram is exactly
  their difference, asserted in `tests/unit/cards/test_dual_macd.py`). The
  histogram alone shows how wide the gap between the lines is but not where the
  crossing sits relative to zero — the difference between a momentum turn inside
  a trend and an outright trend flip. Two new series fields,
  `fast_macd_line_atr` / `fast_macd_signal_atr`, computed in
  `dual_macd_series` and carried in the `technical_daily` metrics JSONB. The
  slow 55/89/34 pair stays histogram-only: it is structural background, and four
  lines in a 150px pane is noise. **Existing rows need a technicals recompute**
  before the lines appear — the new keys are absent from already-stored JSONB.

### Removed

- VP BUY/SELL/touch/reject marks, before they ever shipped in a release. They
  redrew 21% of mark history per day at a 360-bar window and essentially all of
  it on the worst 10% of days, and the levels underneath them carry no measured
  edge. An arrow labelled BUY that moves tomorrow and predicts nothing implies a
  signal the data does not support. The profile, POC, value area and zones stay
  as descriptive structure.
## [0.10.9] — 2026-07-20

### Added

- Dispersion context readout on the CRI regime subtab (`/regime/cri`): a
  descriptive tile row (COR1M 20yr percentile, VIX/COR1M ratio, trailing-252
  ratio z-score). New read-only endpoint `GET /api/regime/dispersion`
  (`VolIndexRepository.fetch_dispersion_context` — 20yr percentile computed
  server-side, so no 20yr series ships to the browser) feeds
  `web/components/regime/DispersionTiles.tsx` via a local-typed
  `useDispersion` hook. A **two-tailed rule-based color highlighter** marks
  regime state — amber = dispersion (low correlation / high single-stock vol),
  red = herding (high correlation, crash-adjacent) — with a legend; it
  deliberately does NOT paint low correlation as a warning. Still explicitly
  regime **context, not a signal**. Backed by the directional evaluation in
  `docs/research/2026-07-19-dispersion-signals-eval.md`, which **rejected** the
  "low correlation (VIXEQ/VIX high) = warning" claim (low correlation is the
  calmest forward regime — shallowest drawdowns; high correlation is the crash
  marker already in the CRI trigger) and found the "deleverage high-beta on
  high VIX/COR1M" claim directionally sound but statistically underpowered
  (~5yr SPHB/SPLV). No new subtab, no new trading signal.

## [0.10.8] — 2026-07-19

### Added

- Chanlun overlay trust-styling on the Technicals price chart: divergence
  markers now reflect the trust-probe findings
  (`docs/research/2026-07-18-chanlun-trust-silver`). Trend-aligned 顶/底背离
  (底 above / 顶 below the chart's 200-DMA — the higher-conviction subset)
  render at full amber; counter-trend or pre-200-DMA-warmup 背离 dim to
  ~35%/~60%; repaint-prone base 1B/1S arrows (24–34% repaint) dim to ~40%,
  while 2B/3B and segment-level markers are unchanged. A pure
  `divergenceTrend` helper in `web/lib/chanlun.ts` (reusing the shared
  `lib/indicators` `sma`) computes the tier from a 200-SMA of the chart's own
  closes; the marker builder in
  `TechnicalsPriceChart.tsx` applies per-tier alpha via the existing
  `cssVar`-suffix idiom. Client-side only — no backend, API, worker, or
  type-gen change; no new chart primitive or toggle. A legend line explains
  the emphasis and discloses that the 200-DMA is corporate-action-unadjusted
  (so the trend split is unreliable for ~200 sessions after a split — the
  known livewire `adj_close` limitation, verified 0/23 NVDA + 0/17 TSLA tier
  flips against the plotted `SMA200` line).

### Fixed

- Technicals price charts now reserve ten bar-widths between the newest bar
  and the right price axis on initial load and after Reset. The chart's
  `fixRightEdge` setting had silently clamped the configured offset back to
  zero; regression coverage now protects both short- and long-history views.

## [0.10.7] — 2026-07-15

### Added

- Chanlun Phase B: sub-level (区间套) fast-confirm signal lifecycle engine,
  backend-only (no UI, no alert emission). Ports the web `chanlun.ts`/
  `chanlunSeg.ts` compute to Python (`src/uw_scan/chanlun/`: types, stroke
  core, segments, points/divergence/resonance, `compute_chanlun_full`) with
  frozen-fixture golden parity against the TS implementation plus 12
  regression tests for JS→Python porting traps (float/date/sort/None-vs-NaN
  semantics). A new `sources/apex.fetch_bars` client reads 1d and 30m bars
  from apex with an explicit `start` (apex's default-limit window silently
  truncates history otherwise) and never raises. Migration 107 adds
  `chanlun_signal_events` — an append-mostly per-`(ticker, category, kind,
extreme_date, extreme_price)` event log (`storage/chanlun_signal_repository.py`,
  standalone, not folded into `Repository`) driving a pure lifecycle state
  machine (`chanlun/lifecycle.py`): pending → confirmed*sublevel (S1: a
  confirmed same-side 30m vertex lands exactly at the daily extreme, no
  later-arriving 30m vertex beats it) → confirmed_native, with breach,
  20-session staleness, and `|ln(open_d/close*{d-1})| > ln(1.5)`split-boundary invalidation guards (S2 divergence-based sub-level confirm
is stubbed as an unused flag for a future iteration). A nightly`chanlun_lifecycle_scan`job (03:10 ET Tue–Sat, massive-0, gated off by
default via`UW_SCAN_CHANLUN_LIFECYCLE_ENABLED`) walks the watchlist and
a new read-only `GET /api/stock/{ticker}/chanlun/lifecycle` endpoint
  exposes current per-mark state.

  The walk-forward validation probe that was to gate which categories get
  promoted past `confirmed_sublevel` (`scripts/research/chanlun_sublevel_probe.py`,
  10 tickers × ~5.1y of daily+30m bars, committed trace under
  `docs/research/2026-07-14-chanlun-signal-lifecycle/phaseb_probe/`) came
  back **negative**: all four candidate categories — vertex, divergence,
  3B, 3S — failed the ≥70% survival gate in both ticker-halves (actual
  7.5–17.3% survival), with the dominant failure mode being supersession by
  a more-extreme same-side point, ~70% of the time within the very next
  session. The shipped `chanlun_promotable_categories` default is therefore
  **empty** — every mark records its lifecycle transitions (useful as a
  durable event log and for the next rule-revision attempt) but none is
  currently eligible for sub-level promotion; the S1 fast-confirm path
  stays inert until a future rule revision clears the gates.

- Chanlun v2 on the technicals price chart: 线段 (chan.py feature-sequence
  port, both termination cases), 段级中枢 + 段级买卖点, pragmatic 中枢升级
  (consecutive overlapping zones merge to level-2 envelopes), and weekly×daily
  区间套 resonance (★ on confirmed daily 买卖点 with a confirmed weekly
  witness). Compute stays client-side (`web/lib/chanlunSeg.ts`,
  `computeChanlunFull`); the 中枢 primitive is reused unmodified.

- Fix: 买卖点 now actually fire on real data — `markPoints` assumed the
  中枢 exit leg was the breakout leg, but `buildPivots`' "first leg fully
  outside" is structurally always the counter-direction pullback, so every
  1B/1S/2B/2S/3B/3S gate was unsatisfiable (zero marks on AAPL/NVDA; the
  old oracles passed only on geometrically impossible fixtures). 3B/3S now
  mark the exit leg's own end vertex; 1B/1S compare breakout legs
  (`exitLeg − 1`). Also adds 顶背离/底背离 amber-dot annotations (a 笔
  extending past the prior same-direction 笔's extreme on weaker MACD
  area). New realistic-geometry oracles + real-data non-vacuity tests;
  post-fix write-up in §6e of the chanlun research doc.

- Fix: `/api/health`'s freshness block now anchors `consecutive_frozen_nights`
  on the snapshot's own newest `run_date` instead of the DB wall clock —
  `latest_snapshot()` was the last bare `consecutive_frozen_counts()` caller
  left behind by the autoheal-circuit-breaker fix, and its `CURRENT_DATE`
  anchor made the reported streak (and `autoheal_circuit_broken`) shrink as
  the clock advanced past the seeded nights (surfaced as the
  `test_health_autoheal_circuit_broken_includes_eligible_tripped_table`
  date-bomb in CI).

- Technicals price chart gains a 缠论 (Chanlun) overlay behind a header toggle
  (next to the SMA·σ/EMA·BB segmented control, localStorage-persisted):
  笔 stroke polylines (solid confirmed / dashed provisional tail), 中枢 pivot
  rectangles [ZD, ZG] (dashed border while extending), and 三类买卖点 markers
  (1B/2B/3B green, 1S/2S/3S red, "?" suffix on provisional points), all drawn
  on the lightweight-charts price pane. Structure is computed client-side in
  `web/lib/chanlun.ts` (包含处理 → 分型 → 新笔-style 笔 → bi-level 中枢 →
  buy/sell points gated by MACD-area 背驰; 线段 deliberately deferred),
  matching the EMA/Bollinger client-side-indicator precedent. 中枢 rectangles
  render via a new custom series primitive (`web/lib/lwc/chanlunZhongshu.ts`).
  Research + v1 design: `docs/research/2026-07-14-chanlun-tv-view-research.md`;
  unit tests run against a frozen real AAPL daily fixture (2026-01-02→07-10).

- Fix: the data-freshness autoheal circuit breaker now counts frozen-night
  streaks anchored on the job's injected `today` instead of the DB wall clock
  (`consecutive_frozen_counts(as_of=...)`). The `CURRENT_DATE` anchor silently
  shrank the counted streak whenever the caller's day differed from the wall
  clock — surfaced as a date-rolling CI time bomb in
  `test_autoheal_circuit_breaker_stops_retriggering` (green until 2026-07-13,
  deterministic failure after). `/api/health`'s streak enrichment keeps the
  wall-clock default.

- Docs: `docs/masterplan/` — cross-stack vision & blockers review plus the
  per-component master plan (goal ladder Stage 1–4, gaps, open decisions
  D-A..D-E, Stage-1 attack order) for the livewire/signal-lab/apex/argon/xenon
  desk. `CLAUDE.md` gains a condensed "Mission" section (stack role, ladder,
  Stage-1 minimal deliverable = signal→alert pipeline, invariants) with the
  verified option-surface history facts (grid spans 2025-12-26→present under
  UW's ~180-day window).

## [0.10.6] — 2026-07-12

- Technicals Dual MACD is now a native lightweight-charts sub-pane of the price
  chart (pane index 1) instead of a standalone hand-rolled SVG oscillator. It
  shares the price chart's single time scale and right-gutter, so the histogram
  bars are pixel-aligned under the candles and scroll/zoom is locked to price by
  construction (no cross-chart sync). The slow 55/89/34 renders as the muted
  structural background with the fast 13/21/9 tactical bars (green up / red down)
  layered on top. The pane's directional signal badge is now colored across the
  full `trend_state` vocabulary: clean BULLISH / DIP_BUY → green, BEARISH /
  RALLY_SELL → red, and the two transitional states color by structure sign at a
  dimmed shade — DETERIORATING (bull cooling) → dim green, IMPROVING (bear
  recovering) → dim red — so "in transition" reads distinctly from a clean trend
  rather than falling through to neutral grey. A faint dotted zero line marks the
  MACD crossing, and the pane keeps the interpretive caption (structural-vs-
  tactical, DIP_BUY / RALLY_SELL) that the old oscillator carried. MACD is no
  longer a reorderable row in the oscillator stack (it's pinned to the price
  chart); the retired `TechnicalsMacdChart` SVG component and its render test are
  replaced by unit tests on the `macdSignal` classifier and the `MacdLegend` row.

## [0.10.5] — 2026-07-12

- Technicals price pane: MarketSmith volume treatment (previous-close coloring,
  volume MA50 line, HVE/HV1 peak labels, volume buzz readout) and a small
  SMA·σ ⇄ EMA·BB overlay toggle (SMA20/50/200 + ±1.5σ band ⇄ EMA5/20/50 +
  Bollinger 20,2), computed client-side over the full series. Each volume bar's
  opacity is U-shaped in its buzz (volume ÷ MA50) to highlight the extremes:
  bars in line with their MA recede to a muted baseline while both tails — an
  extreme-high blowoff and an extreme-low dry-up — saturate to full opacity so
  they pop (the low tail is steeper so quiet, easy-to-miss bars especially stand
  out). Hue always stays the bar's up/down red/green — never grayed. The per-bar
  low-vol −% labels are hidden by default and reveal one-at-a-time on hover in a
  high-contrast color (they overlapped illegibly when all shown at once, and the
  muted color was invisible on the dark pane); revealing a label does not
  rescale or lift the volume bars. The volume band is taller and its
  bars are anchored to the pane floor (baseline pinned to 0 so they sit on the
  axis instead of floating). Bars keep a readable minimum width: short ranges fit
  the pane edge-to-edge, but a long range (e.g. FULL/5Y) no longer squishes to
  1px — it opens at the latest bars at full width and scrolls horizontally into
  history, with a Reset button in the header to snap back to fit-and-latest.
  Frontend-only.

## [0.10.4] — 2026-07-11

- Technicals price pane migrated to lightweight-charts: candlesticks + volume overlay + filled ±1.5σ band + click-to-anchor VWAP persisted per ticker. `technical_daily` now stores OHLCV (rides the nightly full-recompute; per-ticker auto-fill on first page open), new `technical_vwap_anchor` table, `POST/DELETE /api/stock/{ticker}/vwap-anchor`. The pane is taller (460px), the SMA lines are bolder, and the anchored VWAP now draws in a high-contrast sky blue (`--accent-cool`) at 3px so it reads clearly against the candles/SMAs. The header date follows the newest bar actually plotted, so the live head's forming bar drives it to today rather than pinning to the previous-business-day apex EOD date. Today's forming bar is now a **real intraday candle**: the live technicals job accumulates the session's open/high/low/close from the WS spot it already consumes (open = first fresh print of the ET session, high/low = running extremes, close = latest spot) and serves it as `forming_ohlc` on `/technicals/live`, so today draws as a genuine candle that fills in as the session runs and settles into the EOD bar at close — instead of the zero-range doji that hid on the price line. Every value is a real observed print (no fabricated open); at a frozen/closed market the bar is correctly flat. To guard against an unstable primary (xenon) feed, the live job cross-checks the forming candle against massive's ~15-min-delayed today bar every 15 minutes and heals a divergent read to massive (`source='massive.com'`, `stale=true`) — a **range-containment** test (a delayed close must sit inside the live `[low, high]`), which is robust to the 15-min lag where a naive close-vs-close check would false-positive on normal drift. The live oscillators (ATR-normalized MACD, kinematics) now recompute against the stored OHLC rather than close-only bars, so they line up with the settled daily series. (#256)

## [0.10.3] — 2026-07-10

### Changed

- **Technicals tab UI refinements** — the chart timeframe now defaults to **1Y**
  (was FULL/5Y); the reorderable stack now defaults to **dual MACD first,
  MA-Kinematics second** (the saved-order localStorage key is bumped to `:v2` so
  the new default supersedes any order saved under the original key); and the
  MA-Kinematics chart now tints the **below-zero region as a downtrend zone**
  (a subtle red band from the y=0 line to the plot floor via a new
  `shadeBelowZero` prop on `OscillatorChart`) so any moving-average slope dipping
  under zero reads as falling at a glance — line colors and t-stat weighting
  unchanged. The MA-Kinematics **alignment badge** now names the direction and
  colors by sign — `BULL ALIGN n/3` (green), `BEAR ALIGN n/3` (red), or
  `MIXED ALIGN 0/3` (muted) — instead of a sign-agnostic `ALIGN ±n/3`, so a
  bearish stack reads red at a glance (`OscillatorChart`'s `headline` widened to
  `ReactNode` to carry the colored label).

## [0.10.2] — 2026-07-10

### Added

- **Dual MACD on the Technicals tab** — replaces the single MACD histogram with a
  contrasting long-period (55/89/34) + short-period (13/21/9) ATR-normalized dual
  MACD and apex's tactical state machine (DIP_BUY/RALLY_SELL, trend/momentum-balance,
  confidence). The two histograms ride the existing `metrics` JSONB; the state rides
  the `detail` JSONB (no schema change).
- **Live technicals coverage** — a massive-0 scheduler job (`technical_live_scan`,
  gated by `UW_SCAN_TECHNICAL_LIVE_ENABLED`, default off) splices the live WS spot as
  today's provisional daily close and recomputes the fast-moving technicals (z, RSI,
  dual MACD, RV, kinematics, composite — sigmoid/forward-returns excluded) into a
  latest-only `technical_live` cache (migration 104). The Technicals tab polls
  `GET /stock/{ticker}/technicals/live` every 25s and overlays a LIVE/EOD head across
  every oscillator; stale/absent falls back to the EOD daily payload.
- **5-year technicals history** — the daily-bar fetch and warm-store read now retain
  ~1300 sessions across every technicals series.
- **On-demand technicals compute** — an unavailable ticker's Technicals tab now shows
  a "Compute now" button instead of a dead-end message. It POSTs
  `/stock/{ticker}/technicals/refresh`, which runs the nightly refresh job scoped to
  that one ticker (apex bars → EOD series) and returns the fresh payload so the tab
  renders in place; for a watchlist ticker this also makes it eligible for the 5-min
  live overlay on the next tick. Compute-only (no watchlist mutation); thin history /
  apex-unreachable leaves the tab empty with a note.
- **Technicals tab refinements** — the z-score chart now fills the full 5-year window
  (fetch a warmup buffer so `z_vs_200dma`'s ~324-bar warmup falls off the front); the
  dual-MACD chart gains a SLOW/FAST legend and draws the fast bars narrower than the
  slow overlay; the MA-Kinematics chart is weighted by each slope's t-stat (reliable
  trends bold, noise faded) and carries an ALIGN badge; the forward-return table
  defaults to all horizons with per-column aligned headers; a new return-distribution
  histogram (last 60d returns vs a normal, tails flagged) visualizes skew/kurtosis;
  and the live spot now flows into the price-card header with a LIVE/EOD marker.
  Follow-ups: the LIVE/EOD marker lives only in the price tile now (the duplicate
  page-level badge is gone); the standalone Trend-Reliability panel is dropped (its
  t-stats already live in the MA-Kinematics chart), which now also prints a
  plain-English reading of the current slopes; the forward-return table gains a
  "how to read" guide; the Sigmoid panel charts the fitted logistic against actual
  price (the fit's `actual`/`fit` arrays are surfaced only when the fit is valid,
  else the panel stays blank); and the chart stack is reorderable by drag-and-drop,
  with the order persisted per-browser in `localStorage`. The reorder handle is
  gone — the whole chart row is the drag source, so the charts stay flush-left
  with the KPI strip instead of being nudged over by a handle gutter. The Sigmoid
  panel's rejection message now names the clause that actually failed (fit too
  weak vs. no better than a straight line vs. curve pointing the wrong way)
  instead of a fixed formula that could read as the false "0.31 ≤ 0.05 + 0.05",
  and gains a how-to-read guide explaining the S-curve, phases, and k/s/R². The
  anchor price chart is now pinned at the top of the stack (out of the reorderable
  set — it's the date-axis alignment reference) and carries a theme-styled
  timeframe selector next to its date badge: FULL (5Y) / 1Y / YTD / 3M windows
  every date-axis chart below at once (a pure client-side slice of the series
  already in the payload — no extra fetch). The return-distribution panel keeps
  its own fixed 60d sample (it's a shape, not a date-axis graph the window pans).

## [0.10.1] — 2026-07-09

### Fixed

- **Schema-bearing releases now auto-migrate on deploy.** The engine-wide
  Watchtower deploys new _images_ but never ran the profile-gated `migrator`, so
  a release that added a table shipped code against an un-migrated DB until a
  human remembered to apply migrations (v0.10.0's `technical_daily` was missing
  for ~7h — api stayed green while the Technicals tab 500'd). The `api` service
  now self-migrates (`migrate_runner && exec uvicorn`) before serving: it is the
  single migration owner (no racing DDL across the sharded workers), never serves
  against an un-migrated schema, and crash-loops loudly on a bad migration instead
  of silently partial-serving. Idempotent + ~1s, so re-running every boot is free.
  Activation is a one-time `/opt/argon/compose.yml` mirror + `up -d api` (Watchtower
  does not deploy compose changes); future image-only releases self-migrate.
- **VRP macro entry-capture legs now snap to real Δ0.25/Δ0.125, not flat-vol
  strikes.** `resolve_entry_contracts` selected strikes off a single ATM/VIX vol,
  so SPX put skew made the recorded legs systematically too shallow (Δ~0.28 short
  / ~0.17 wing instead of 0.25 / 0.125) — the tracked strikes sat well above the
  legs you'd actually trade. Selection is now skew-aware: it brackets each target
  in delta-space using each strike's _own_ IV. The nightly
  `vrp_macro_entry_grid_refresh` caches the per-strike IV map alongside the strike
  grid (`vrp_macro_entry_grid.strike_ivs` JSONB, migration 103) so both the RTH
  auto-birth and the Capture button stay zero-extra-UW; a legacy grid without the
  IV map falls back to the old flat-vol path. To re-capture today on the corrected
  strikes, refresh the grid first (populates the IV map), then click Capture.

## [0.10.0] — 2026-07-09

### Added

- Technicals tab on `/stock/[ticker]` (index 1, after Market Structure): KPI stat-strip, price/MA/±1.5σ anchor chart, z-vs-200DMA history, forward-return-by-z-band table with current-band highlight, MA-kinematics / sigmoid / distribution / RSI / MACD / SPY-RS panels. Client island off the SingleStockReport hot path.
- Technicals metric history persisted per session (`technical_daily.metrics` JSONB, migration 102): return-distribution moments, RSI z/slope, MACD slope, MA-kinematics slopes, alignment.
- Technicals tab reorganized into an aligned stacked-panel layout (trader-terminal style): price/MA/±1.5σ anchor on top, then Z-score, RSI(14), MACD histogram, realized-vol, MA-kinematics, and relative-strength as full-width sub-charts sharing one date axis and left gutter (columns line up with price), each with a y-axis, reference lines/zones, and a plain-English explanation. Scalar-only diagnostics (MA-slope t-stats, alignment, sigmoid maturity, distribution shape) render as explained readouts. Sigmoid stays latest-only (per-request curve fit).
- Technicals backend: `technical_daily` warm store (migration 101), pure derivers in `cards/technicals.py` (z-vs-200DMA + bands, MA kinematics, sigmoid trend-maturity with beats-linear guard, return distribution, RSI/MACD enhanced, SPY relative strength, forward-return-by-z-band table), `GET /api/stock/{ticker}/technicals`, nightly `technical_daily_refresh` (apex daily bars, massive-0 18:40 ET, `UW_SCAN_TECHNICALS_REFRESH_ENABLED`).

### Changed

- **`/stock/{ticker}` performance package — three compounding fixes on the app's
  busiest read path.** (1) Killed an N+1: `_build_intraday_profiles` issued one
  `option_intraday_buckets` query per top-10 OI mover (10 serial round-trips per
  page load); new `OptionIntradayBucketRepository.fetch_buckets_batch` collapses
  them to a single `unnest`-join query. (2) Added a per-`(ticker, run_id)` TTL
  response cache in front of `assemble_single_stock_report` (default 20s, set
  `SINGLE_STOCK_REPORT_CACHE_TTL_S=0` to disable) so revisits and the 2.5s
  watchlist-spot poll don't re-derive the whole report; callers get a deep copy so
  the header's live-spot mutation can't corrupt the cache. (3) Replaced the
  connect-per-request path in `api/deps.py` with a process-wide
  `psycopg_pool.ConnectionPool` (`UW_SCAN_DB_POOL_MIN`/`_MAX`, default 2/10) —
  removes per-request TCP+auth+`SET search_path`, which matters more now that the
  api container reaches Postgres across the Docker VM boundary. Added `psycopg`'s
  `pool` extra.
- **Request-timing monitor for our own endpoints.** New log-only ASGI middleware
  tags every response with `X-Response-Time-ms` and logs a WARN when a request
  exceeds `API_SLOW_REQUEST_MS` (default 500; 0 silences). Distinct from the
  existing outbound-UW `latency_p95_ms`. Cache hit/miss counters exposed via
  `report_cache_stats()`.

- **Docker migration — cutover complete (Phase 2) + launchd retired (Phase 3).**
  argon now runs in Docker on the mini (`/opt/argon/compose.yml`); the 14 launchd
  app plists are moved to `/opt/argon/retired-launchd-plists/` (only
  `com.argon.backup` stays host-native), and deploys flow through the engine-wide
  Watchtower instead of the launchd `deploy-poller`/`macmini-prod.sh` path. Updated
  `docs/runbooks/docker-deploy.md` (status → complete, rollback path) and the
  CLAUDE.md release procedure. Rollback restores the plists from the retired dir.

### Fixed

- **Docker web healthcheck triggered a recurring `transformAlgorithm` error.**
  The compose web healthcheck used `wget --spider` (a HEAD request); a HEAD against
  the streaming SSR landing page makes Next.js 16 on Node 22 wire a response
  `TransformStream` with no body, logging a caught, non-fatal
  `controller[kState].transformAlgorithm is not a function` every 30s. Switched the
  healthcheck to a full GET (`wget -qO /dev/null`), which drains the body → zero
  such errors (verified live). Real user GETs were never affected. Also corrected
  the compose header container count (12 → 10).

## [0.9.1] — 2026-07-08

### Fixed

- **Docker web image: client-side `/api/*` rewrite baked the wrong target.**
  `next.config.mjs` `rewrites()` is evaluated at _build_ time, so the CI-built
  `argon-web` image froze the `localhost:8400` fallback into its standalone
  server — every browser `/api/*` call 500'd in-container (SSR was unaffected,
  masking it). `docker/web.Dockerfile` now sets `ARG NEXT_INTERNAL_API_BASE=`
  `http://api:8400` before `next build` so the rewrite bakes the compose
  service name; the launchd (non-Docker) build still bakes its correct
  co-located `localhost` default. Runbook Phase 2 gains an explicit
  web→api rewrite check (SSR page codes pass even when this path is broken).

## [0.9.0] — 2026-07-08

### Added

- **Docker migration — prep (artifacts only; no cutover yet).** Ships the pieces
  to move the mini prod stack off launchd into Docker (xenon/apex house pattern:
  Colima, `host.docker.internal`, host-native Postgres, GHCR images, the shared
  engine-wide Watchtower): `docker/app.Dockerfile` + `docker/web.Dockerfile`,
  root `docker-compose.yml` (10 services), `.dockerignore`, and a `ghcr-push`
  matrix job in `release.yml` (builds/pushes `argon-app` + `argon-web` to GHCR on
  every tag; `:latest` floats only for final releases). `config._HOST_DB_RULES`
  gains a `host.docker.internal` rule so containers pass the DB-isolation
  tripwire without the blanket override. Web SSR fetch sites now read the runtime
  `NEXT_INTERNAL_API_BASE` (not the build-inlined `NEXT_PUBLIC_API_BASE*`) so a
  containerized web renders against the `api` service, not itself; `next.config`
  emits `output: 'standalone'` with `outputFileTracingRoot` pinned to `web/`.
  **The launchd stack remains the live prod path** — cutover is phased and
  user-driven (`docs/runbooks/docker-deploy.md`,
  `docs/superpowers/specs/2026-07-06-docker-migration-design.md`). AI Codex/Claude
  workers are retired in phase 1 (issue #248); DeepSeek survives.

## [0.8.1] — 2026-07-08

### Changed

- **Mac mini Postgres backups now target the DATA_LAKE volume, atomically, on
  pg17.** `com.argon.backup` (and the R2 uploader) write to
  `${ARGON_BACKUP_DIR:-/Volumes/DATA_LAKE/argon/postgres-backups}` instead of the
  repo's `data/backups/`, dump via `postgresql@17` (matching the mini's server),
  and write to a `.part` file renamed into place only on success so a crashed
  `pg_dump` never leaves a truncated-but-plausible dump. `macmini-bootstrap.sh`
  now scaffolds the mini `.env` for same-host Postgres (`UW_SCAN_DB_HOST=127.0.0.1`
  - `UW_SCAN_ALLOW_DB_MISMATCH=1`) rather than routing over Tailscale. Runbook
    documents the macOS TCC `RemovableVolumes` requirement (background launchd jobs
    cannot write removable volumes without it) plus a shape-test probe to verify it
    after OS upgrades. Config/ops only — no application code paths change.

### Fixed

- **Deploy health-gate no longer deadlocks on benign budget-throttled scans.**
  The v0.7.2 change gated deploy success (and rollback verify) on `/api/health`
  `.ok == true`. But `.ok` folds in "expected full scans missed", which is
  routinely false for a _benign_ reason — UW daily-budget exhaustion legitimately
  **skips** full scans for most of the trading day, so the whole health reports
  `ok=false`. With `.ok == true` required on _both_ the forward gate and the
  rollback verify, a deploy launched during a budget-throttled window can pass
  neither: it burns its retry budget, rolls back, the rollback verify also fails,
  and the outer `gtimeout` kills `macmini-prod.sh` (rc=124). This is exactly how
  the v0.8.0 deploy failed and stranded the mini on v0.7.2. The gate now asserts
  **serving liveness** — `.db == "up" and .version == "<VERSION>"` (DB reachable +
  the newly-deployed code is the process actually answering) — and the rollback
  verify asserts `.db == "up"`. Worker/scan health stays monitored separately
  (C12 job-failure streaks + heartbeats); it is no longer conflated with whether a
  build deployed correctly.

## [0.8.0] — 2026-07-08

### Added

- **Ops-hardening: detection + alerting layer (C12 Track A).** Three pieces that
  make the ops surface observable before the Docker/Watchtower cutover (Track B).
  (1) **Job-failure streaks** — a new `job_failures` table (migration `100`) plus
  an APScheduler `EVENT_JOB_ERROR`/`EVENT_JOB_EXECUTED` listener records per-job
  consecutive-failure streaks (reset on success); surfaced on `GET /api/health`
  as `job_failures`. (2) **Per-job UW budget attribution** — the external-API
  breakdown now groups by `job_name` too, exposed at `GET /provider-usage/jobs`.
  (3) **Webhook alert sink** — a single never-raising `send_alert(title, message)`
  (`src/uw_scan/alerts.py`) fires on a failure streak reaching 3 (then 10) and
  once/day at the account-wide UW budget wall. **Set `UW_SCAN_OPS_ALERT_WEBHOOK_URL`
  in the mini `.env` to enable alerts** (Discord/Pushover-compatible JSON POST);
  unset = no-op by design. Alerting is fire-and-forget and can never crash the scheduler or
  the budget governor. R2 lake-staleness monitoring (ops-hardening spec §3) is
  intentionally out of scope.

## [0.7.2] — 2026-07-07

### Added

- **UW same-day fetch dedupe memo (issue #225).** The shared UW daily budget is
  exhausted by ~08:00 ET partly because 6+ jobs (option*surface_capture,
  cockpit_daily_snapshot, flow_data_refresh, skew_swing_greeks, vrp_macro_entry,
  full_scan pipeline) independently re-fetch identical slow-moving per-ticker data
  every day. The budget governor gates \_spend* but does not _dedupe_. New
  Postgres-backed memo (`uw_fetch_memo`, migration `099`; `storage/uw_fetch_memo.py`)
  keyed `(ticker, endpoint, as_of_date)` is consulted in `sources/uw.py` BEFORE the
  live call: the first same-day caller of `fetch_option_contracts` /
  `fetch_greek_exposure_by_expiry` spends budget and stores the raw payload; every
  same-day caller after reads it back (a budget SAVE, recorded on the row's
  `hit_count` + `last_hit_at`). TTL = same trading day (a row for today is a hit;
  stale dates are ignored and prunable). DB-backed rather than in-process because the
  jobs run in separate worker processes. Only the two slow-moving endpoints are
  wrapped — intraday/live feeds (spot, flow alerts) stay fresh — and both fetchers
  take a `force_refresh=True` kwarg to bypass. The historical-`date` path of
  `fetch_greek_exposure_by_expiry` is never memoized.

### Fixed

- **Market Tide tab froze mid-session when the shared UW account hit its guard.**
  `_regime_market_tide_scan` was budget-gated via `_research_budget_ok`, which
  returns False once the account-wide `official_daily_count` crosses
  `uw_total_daily_guard` (105k) — a threshold the shared UW key crosses most days
  by mid-morning (co-tenant + always-on stack). So the 5-min tide capture stopped
  appending bars (frozen at the prior session) even though it costs just **1 UW
  call/tick (~78/day)** — spot comes from the WS DB table, not UW. Dropped the gate
  to match its identical-cost sibling `regime_top_net_impact_scan` (never gated).
  Expensive intraday research (`regime_gex_scan`, ~4k calls/day) stays gated.

- **Deploy health-gate now checks `ok`, not just reachability.**
  `scripts/deploy/macmini-prod.sh` gated deploy success (and auto-rollback) on
  `curl -fsS` against `/api/health` — but that endpoint returns HTTP 200 in every
  branch, including `ok=false` (db down, missed scans, record-coverage collapse), so
  a broken release passed the gate clean and rollback never fired. `check_url` now
  takes an optional jq filter; the api gate and the post-rollback verify both require
  `.ok == true`. (jq already a deploy dep via `macmini-deploy-poller.sh`.)

### Added

- **Flow vs RV−IV falsification — do UW-native flow signals survive residualization? (#227, research spike).**
  `scripts/research/flow_vs_rviv_verdict.py` — residualizes a 3-day aggressor
  premium-imbalance signal (+ dealer net vanna / net charm) cross-sectionally against
  RV−IV, then decile-sorts forward 1d/5d stock returns on the RESIDUAL vs a
  matched-window RV−IV benchmark, gross and net of cost. **Verdict: NEGATIVE
  (coverage-limited but directionally clean).** On the fair matched-day benchmark, plain
  RV−IV does as well (1d: ~122 vs ~128 bps, a tie) or dwarfs the flow residual (5d: ~826
  vs ~340 bps); scattered |t|~2–3 cells are sign-inconsistent across horizons/signals and
  of implausible magnitude — small-sample noise on ~11–21 non-contiguous days, not a
  distinct tradable axis. Goyal–Saretto's collapse-to-RV−IV extends to aggressor flow and
  vanna/charm. Local `option_wizard_local` window: flow_events 114 tickers × 31 days
  (2026-05-12..07-07, two multi-day gaps); exposures_summary 115 × 22 days. Full trace in
  `docs/research/2026-07-07-flow-vs-rviv-verdict.{result.md,summary.json,daily_ls.csv}`.
  Re-run on the mini's fuller history before over-trusting the tie at 1d. Read-only, no
  migration.
- **Positioning intelligence — surface `uw_positioning` (card + screener).**
  The daily-banked `uw_positioning` snapshot (short interest / %float / days-to-cover /
  borrow fee, analyst counts + targets, institutional counts/value, insider net flow,
  earnings-reaction base rate, next ER date) previously had exactly one reader (the
  trade-blast LLM prompt) and no endpoint, panel, or screener. Now exposed read-only:
  `GET /api/positioning/{ticker}` (full snapshot + derived signals) and
  `GET /api/positioning/screener` (one row per watchlist ticker, sorted by squeeze
  risk). Derived signals (computed at read time in `reports/positioning.py`): squeeze
  score/label (si*pct_float × days-to-cover × borrow-fee tiers), insider net-flow tilt,
  analyst implied upside vs spot, analyst rating skew, pre-ER positive-reaction base
  rate, days-to-next-ER. Web: a Positioning card on the stock page's Market Structure
  tab + a `/positioning` screener table (new sidebar entry). **Zero new UW fetch** —
  everything reads the existing warm store. Storage read queries live in
  `storage/positioning.py` (`list_uw_positioning_latest`); models in
  `models/positioning.py`. Follow-ups deferred: parsing the discarded 13F/insider
  `raw_jsonb` detail, a borrow-fee \_spike*-vs-baseline signal (needs a rolling read),
  and any cross-sectional alpha signal (this is a surfacing task, not an alpha probe).
- **Trade-lifecycle layer: VRP-macro entry-capture cohorts read back as a portfolio (#223).**
  The validated VRP-macro edge captures entries into `vrp_macro_entry` (8 marks/day ×
  30 cal-days per cohort) but nothing read them back. New `/api/positions` (list) and
  `/api/positions/{entry_id}` (per-cohort P&L curve) endpoints surface every cohort
  (auto + button, open + expired) with its entry credit, latest mark, running unrealized
  P&L, return-on-risk, and DTE/expiry status — all modeled from the persisted
  short_above/wing_above bull-put mids (a missing NBBO side yields a null credit, never a
  fabricated number). New web **Positions** page (`/positions`, sidebar entry) renders the
  portfolio table with an expandable hand-rolled-SVG P&L curve per cohort. Pure read: two
  new storage queries on `storage/vrp_macro_entry.py`, a pure `reports/vrp_lifecycle.py`
  assembler, and `models/vrp_lifecycle.py` contract models — no new tables/migration.
  Reproduce/verify: `UW_SCAN_DB_USER=<superuser> UW_SCAN_DB_HOST=127.0.0.1
UW_SCAN_TEST_DB_NAME=option_wizard_test_wt1 UW_SCAN_ALLOW_DB_MISMATCH=1 uv run pytest
tests/unit/test_vrp_lifecycle_report.py tests/integration/storage/test_vrp_macro_entry_lifecycle.py
tests/integration/api/test_positions_api.py` + `cd web && npx vitest run tests/unit/PositionsPanel.test.tsx`.
- **Implied-correlation / dispersion richness gate — falsified (research spike, #226).**
  `scripts/research/implied_corr_gate.py` tests whether implied-correlation richness is a
  second, near-orthogonal axis on top of the validated VRP-macro short-vol edge. Uses the
  real CBOE **COR1M** implied-correlation index (`vol_index_daily`, 2007–2026, n=244
  non-overlapping SPX bull-put-spread trades) and reuses the validated
  `build_bull_put_spread` P&L + `backtest.metrics` machinery — no reinvented backtest math.
  Verdict in `docs/research/2026-07-07-implied-corr-gate.md`: **NEGATIVE, do not build**
  (MED). Short-vol P&L is **not monotone** in COR-z (inverted-U, top bucket reverts,
  Spearman p=0.29); COR-z is **~80% collinear with VIX-z** and insignificant (t=1.45) on
  independent trades once vrp-z/VIX-z are controlled; a COR-z gate gives no Sharpe gain
  (0.732→0.748) and halves return. The issue's equal-weight top-10 dispersion proxy tracks
  COR1M at pearson 0.91, validating COR1M as the measure. Read-only; no schema change.
- **SVI surface-fit feasibility + residual edge test (research spike).**
  `scripts/research/svi_fit.py` — pure raw-SVI (Gatheral) smile fit + butterfly/calendar
  no-arb diagnostics + delta-forward anchor, unit-tested (`tests/unit/test_svi_fit.py`) —
  plus two read-only probes over `option_surface_grid_daily`. Verdict in
  `docs/research/svi-surface-fit/`: raw-SVI fits liquid smiles to <0.5 vol-pt residual,
  arb-free, but the fitted-vs-marked residual — while a genuine mean-reverting signal
  (autocorr 0.56) — carries **no taker edge** (~\$0.18/contract, below one option
  commission). Do not build the signal layer. Adds `scipy` (main dep, needed by the tested
  fit); figs use matplotlib from the existing `research` dep-group. Also surfaced: the
  mini's IB canary (`iv_source_validation`) had captured no IB IV (0/1026 rows) through
  07-02 — a stale pre-key env frozen at worker fork, not a missing key (the mini's argon
  `.env` has `XENON_QUERY_API_KEY`); the Jul 4 worker restart already picked up the key,
  so the canary should self-heal on its next weekday run.
- **LEAP vega-alpha feasibility (research spike).** Tested radon's "cheap LEAP" thesis
  (HV20/HV60 − LEAP ATM IV wide ⇒ long-vega alpha) on 6 months of banked
  `option_surface_grid_daily` + apex daily bars. `scripts/research/leap_vega_alpha.py` —
  pure lib (realized vol, interpolated-δ ATM IV, entry gap, pooled + Fama-MacBeth
  cross-sectional metrics), unit-tested (`tests/unit/test_leap_vega_alpha.py`, 10 tests) —
  plus two read-only probes (convergence + P&L). Verdict in `docs/research/leap-vega-alpha/`:
  **NO tradable vega edge.** Stage 1 shows a real cross-sectional relationship (single-name
  FM IC 0.34/0.43), but Stage 2 decomposes the flagged "cheap LEAP" P&L as **82–88% delta**
  (a directional bet on high-vol names in an up-market); the delta-hedged, theta-net vega
  edge is **0.6–0.7 vol points — below the 1–5 vp ATM-LEAP round-trip spread**. Greek units
  calibrated empirically (grid `call_vega` is per-1%-vol, `call_theta` per-day — the
  CLAUDE.md "vega ×100" note is wrong for this table). Matches argon's prior: single-name
  surface geometry carries no taker edge (cf. skew #208, SVI #219). Zero UW/IB calls.

## [0.7.1] — 2026-07-04

### Fixed

- **HealthPanel "API OFFLINE" flicker.** The sidebar rapidly toggled `API
OFFLINE` / everything `UNKNOWN` even while the API was up. Root cause: the
  `/api/health` record-coverage ("Query Coverage") scan costs ~15–20s cold but
  its cache TTL was only 15s, so a fresh 20s query fired on nearly every 5s
  poll, stacking on one DB and blowing the browser fetch timeout. Two changes:
  (1) `_RECORD_HEALTH_CACHE_TTL_SECONDS` 15→120 so the expensive scan runs at
  most once every 2 min; (2) the poll now caps each request at an 8s timeout and
  keeps the last-good snapshot on a transient miss, only showing `OFFLINE` after
  3 consecutive failures (a real outage) instead of flickering on one slow poll.
  Polls are serialized (next scheduled only after the current settles) so an 8s
  timeout under a 5s interval can't overlap and let a stale timed-out poll
  corrupt the consecutive-failure count.
- **HealthPanel "Query Coverage" permanently ALERT.** The record-coverage check
  auto-discovered every ticker+timestamp table and expected ~90% watchlist
  coverage in an 8h window, with no market-calendar awareness — so it flashed
  ALERT every weekend/holiday/overnight (no scans run → 0 rows) and, during RTH,
  for sparse/research tables that structurally never reach 90% coverage. Now:
  (1) the check is market-calendar aware — when no full-scan cron was due in the
  window it reads healthy and skips the per-table scan (mirrors the WS-consumer
  relaxation); (2) the structurally-sparse candidate / research / unusual-activity
  tables (`signal_hits`, `scanner_candidate_snapshots`, `vrp_trade_candidates`,
  `vrp_paper_positions`, `vrp_backtest_trades`, `vrp_macro_sweep_results`,
  `corporate_actions`, `iv_source_validation`, `short_interest_snapshots`,
  `flow_events`, `dark_pool_events`, `oi_change_events`) are excluded — the
  event tables insert nothing for a ticker with no events, so they never reach
  90% coverage (but `signal_gates` is kept — it is written once per scanned
  ticker, so its coverage is a real scanner-persistence signal); (3) the nightly
  `option_surface_grid_daily` / `flow_alerts_daily_rollup` tables use the 24h
  window instead of 8h.

## [0.7.0] — 2026-07-04

### Added

- **UW daily-budget governor + RTH cadence scale-up** (targets ~70k live / ~25k
  research under the shared 120k account cap). New `sources/uw_budget.py` reads
  today's UW spend from `external_api_requests`, splits jobs into a `live` pool
  (`full_scan`, `full_scan_hot`, `rescan_tick`) and a `research` pool (everything
  else incl. `*_backfill`), and enforces per-pool ceilings plus an account-wide
  total guard (from the `official_daily_count` header, which also sees
  un-instrumented consumers). Under budget pressure `full_scan` scans hot-first
  and drops the cold tail (`max_tickers` cap) instead of 429-storming; research
  jobs yield first. Env: `UW_BUDGET_GOVERNOR_ENABLED`, `UW_LIVE_DAILY_CEILING`
  (80000), `UW_RESEARCH_DAILY_CEILING` (30000), `UW_TOTAL_DAILY_GUARD` (105000),
  `UW_DAILY_LIMIT` (120000).
- **Hot-subset fast lane** — a per-ticker `hot` flag (migration 096, UI toggle
  mirroring the pin: `HotButton` + watchlist hot-slots meter). Hot tickers get a
  tight-freshness intraday `full_scan` (`full_scan_hot` job, `*/5 9-16` ET,
  primary-uw-only, governor-capped). Env: `FULL_SCAN_HOT_ENABLED`,
  `FULL_SCAN_HOT_CRON`, `FULL_SCAN_HOT_STALE_MINUTES`, `FULL_SCAN_HOT_MAX_TICKERS`.
- **Intraday GEX research series** — `regime_gex_scan` expanded from the
  SPX/SPY/TLT core to the index family + M7 and moved to a split RTH-fast
  (`*/2`) / off-hours-slow (`*/15`) weekday cadence, building the append-only
  intraday GEX/DEX series UW only serves at EOD. Env:
  `GEX_SCAN_RTH_INTERVAL_MINUTES`, `GEX_SCAN_OFFHOURS_INTERVAL_MINUTES`,
  `GEX_SCAN_TICKERS`.

- Unified backtest harness `src/uw_scan/backtest/` (no-lookahead replay engine,
  time-ordered holdout splitter, walkforward+quarter OOS gates, legacy-convention
  metrics, persist-as-you-go sweep runner) + migration 095
  (`backtest_sweep_runs`/`backtest_sweep_results`). `skew_markout`, `vrp_markout`,
  `vrp_markout_core`, and `vrp_backtest` gate/holdout logic is now fully
  deduplicated onto it (behavior-identical) — no private copies remain;
  `scripts/_vrp_macro_param_sweep.py` synthesis grid now persists its full trace.

### Changed

- `full_scan_stale_after_hours` is now a float defaulting to **0.33** (~20-min
  watchlist freshness, was int `1`). `UW_SCAN_FULL_SCAN_STALE_HOURS` accepts
  fractional hours. The health "expected full scans missed" liveness alarm is
  now decoupled from card freshness onto its own grace knob
  (`health_full_scan_missed_grace_hours`, default 1.0h) so a transient
  governor-driven skip no longer false-alarms; sustained live-budget starvation
  (>1h) still alarms, as it should. The benchmark coverage gate
  (`benchmark/collector.py`, same `>=2` missed-scan threshold) shares the knob so
  the two "missed scans" signals stay consistent.
- Backfill scripts (`market_tide`, `greek_exposure_daily_refresh`,
  `intraday_buckets`, `option_surface`) now route UW calls through
  `ExternalApiRequestRecorder`, so their spend is attributed to the research
  pool and visible to the governor (Phase 0).
- **CLAUDE.md refresh + AGENTS.md deduplication.** All 14 in-repo CLAUDE.md
  files audited against the current tree and de-staled (api routers 6→17,
  cards/reports rewritten as domain-group maps, worker's dead
  `jobs/spot_refresh.py` entry removed, web stock `[tab]/` router + `/rates`
  `/vrp` routes documented, tests layout corrected). Four standing rules
  promoted from session memory (CHANGELOG-rides-the-feature-PR, smoke tests via
  the real worker path, R2-primary for EOD/backfill, workers-don't-hot-reload).
  `AGENTS.md` is now a symlink to `CLAUDE.md` (its two unique lines — worktree
  location rule, `unusual_whales_api_spec.yaml` pointer — were merged in first).

## [0.6.0] — 2026-07-02

### Added

- **Gold/rates tables added to the daily freshness monitor.** `etf_flows_daily`,
  `wgc_etf_monthly`, `cb_gold_reserves_monthly`, and `exchange_inventory_daily`
  join `MONITORED_TABLES` (`/api/health` `freshness` block, nightly
  `data_freshness_monitor`) — none were previously monitored, which is why
  `etf_flows_daily`'s ~7-week silent staleness (fixed in v0.5.1) required a
  manual investigation to catch instead of surfacing automatically.
  `_DATE_COL_PREFERENCE` now recognizes `obs_date`/`obs_month` (the gold/rates
  convention, distinct from the options-chain `market_date`/`trade_date`).
  `MonitoredTable` gains a per-table `grace_days` override so monthly-cadence
  sources (WGC releases monthly; COMEX/LBMA vault data is effectively monthly)
  don't cry wolf under the 4-day default meant for daily options data.
  `wgc_etf_monthly` / `cb_gold_reserves_monthly` / `exchange_inventory_daily`
  will show `frozen=true` until someone provisions a `WGC_GOLDHUB_COOKIE` or a
  licensed COMEX data source — that's accurate, not noise.
- **Freshness monitor coverage expanded from 12 to 48 tables.** A follow-up
  audit of the full 118-table data-gap registry found ~40 more genuinely
  continuous tables with zero prior `/api/health` visibility: the durable
  option-surface IV grid, the options-chain pipeline (greeks/IV term/skew/max
  pain/exposures), regime scanner outputs (GEX/CRI/VCG/GRG/canary), and the
  remaining FRED/rates/gold sources not already known to be blocked.
  `_DATE_COL_PREFERENCE` now also recognizes `data_date` and `snapshot_date`.
  `MonitoredTable` gains a `date_col_override` for the handful of tables with
  a one-off column name (`auction_date`, `record_date`, `event_date`) rather
  than growing the shared preference list with names that could collide on a
  future table. Deliberately **not** added: `dark_pool_events`, `flow_events`,
  `option_contract_snapshots`, `massive_fundamentals`, `short_interest_snapshots`
  (no DATE-typed column, only TIMESTAMPTZ event/insert timestamps —
  `compute_freshness` only handles DATE columns today) and `corporate_actions`
  (has both a date and ticker column, but is genuinely event-sparse per ticker;
  watchlist-scope coverage would produce a permanent false LOW COVERAGE
  warning, not a real signal).
- **Freshness grace periods derived from each table's real cadence, not hand
  guesses.** `MonitoredTable.grace_days` now defaults to a lookup on the
  gap-healer registry's `expected_frequency` (`_FREQUENCY_GRACE_DAYS`:
  equity_session/daily → 4, weekly → 10, monthly/event → 45) instead of each
  table separately guessing its own number — the exact class of manual
  judgment that caused 4 real scoping bugs earlier in this same pass (see
  "correct scope for 4 index/regime-only tables" below). Also fixes the
  registry itself: `wgc_etf_monthly`, `cb_gold_reserves_monthly`,
  `exchange_inventory_daily`, `rates_cftc_tff_weekly`, and
  `rates_treasury_auctions` were defaulted to `expected_frequency=
"equity_session"` despite being monthly/weekly; `rates_policy_events`
  becomes `"event"` (FOMC-driven, no fixed periodic SLA).
- **Freshness-autoheal: a same-night retry with a circuit breaker.** A frozen
  table with a gap-healer adapter gets one scoped retrigger the same night
  (`DATA_FRESHNESS_AUTOHEAL_ENABLED`, off by default) — a second chance for a
  table the 20:00 ET gap-healer left frozen from budget exhaustion or a
  transient failure, not a substitute for that nightly job. A circuit breaker
  (`DATA_FRESHNESS_AUTOHEAL_CIRCUIT_BREAKER_NIGHTS`, default 3 consecutive
  frozen nights) stops retriggering a genuinely unfixable source (missing
  credential, licensed data feed) instead of burning budget on it forever;
  tripped tables surface on `/api/health` (`freshness.autoheal_circuit_broken`)
  so a human knows to step in. Verified against a dry-run on real prod data:
  of today's 3 frozen tables, 2 have no adapter at all and the third would
  already have its circuit breaker tripped — autoheal correctly does nothing
  for any of today's known-broken sources.

### Removed

- **Dropped 4 permanently-empty legacy tables and their dead code paths**
  (migration `094`): `option_surface_snapshots` (S1 placeholder superseded by
  `option_surface_grid_daily`), `scan_universe` + `scan_results` (S2 full-scan
  persistence for a since-deleted Streamlit prototype — only reachable from
  an integration test, never from a scheduler job or the live Scanner page),
  and `structure_ideas` (a trade-structure stub whose writer had zero
  callers). Removed the now-dead `pipeline.run_full_scan`, `reports/scan.py`,
  `scan_universe.py`, five `_ScanResultsMixin` methods, `insert_structure_idea`,
  a dead marketcap-fallback join in `storage/watchlist.py`, and the
  corresponding registry/test entries. The live Scanner page is unaffected —
  it reads `scanner_candidate_snapshots` / `signal_hits` / `signal_gates` /
  `signal_context_flags`, none of which touch these tables.

## [0.5.1] — 2026-07-02

### Fixed

- **`gold_etf_holdings_ingest_job` used the host's local clock instead of ET.**
  `date.today()` picked up the mini's system-local date (ahead of US Eastern by
  ~12h) to compute the UW `/etfs/{ticker}/in-outflow` date range, so on a host
  whose local day has already rolled past midnight ET, `end_date` became a
  "future EST date" and UW rejected every call with HTTP 422 — silently, since
  the fetch is wrapped in a per-ticker `try/except: logger.warning`. `GLD` /
  `IAU` / `GLDM` in/outflow data (`etf_flows_daily`) stopped refreshing as a
  result. Now computes "today" via `datetime.now(ZoneInfo(rth_tz))`, matching
  the ET-aware pattern already used by `flow_data_refresh`, `regime_live`,
  `vrp_macro_signal`, and others.
- **xdist sharding blind spot** — `_reset_to_baseline` in `tests/integration/conftest.py`
  now drops any tables the test under execution created that are not in the
  post-migration baseline snapshot, before the `TRUNCATE … CASCADE` restore.
  Previously, an ad-hoc `CREATE TABLE` inside a test survived across tests within
  the same xdist worker and was only exposed by the unsharded release-verify gate
  (which runs the full suite serially in a single DB). The fix kills the whole
  class: drop extras → truncate baseline → copy baseline back.
- **`macmini-prod.sh` npm ci flakiness** — `rm -rf web/node_modules` is now run
  before `npm ci` so a partially-written `node_modules` (e.g. the `ENOTEMPTY:
rmdir lucide-react/dist/esm` error that blocked the first v0.5.0 deploy attempt)
  cannot stall the build step and leave the deploy script mid-way through
  `set -euo pipefail`.

## [0.5.0] — 2026-06-30

### Added

- **Data gap healer — full-coverage audit + heal + nightly backfill.** A
  resumable, budget-aware service that accounts for **every** recorded `uw_scan`
  table (118 datasets) and repairs safe coverage gaps. New `data_gap_*` domain
  (`migration 092`): a dataset registry (one source of truth in
  `reports/data_gap_healer.py`, projected to `data_gap_dataset_registry`),
  gaps-only `data_gap_items`, resumable `data_gap_runs`, and no-data
  `data_gap_caveats`. The exact scanner finds per-ticker/date misses by
  set-difference SQL (zero provider calls); the heal dispatch maps each healable
  dataset to an existing production job via one of four strategies
  (`run_once` / `run_once_lookback` / `per_ticker_range` / `per_ticker_date`).
  CLI `scripts/backfill/data_gap_healer.py` exposes `audit` / `execute` /
  `resume` / `verify` / `verify-all`; every run writes a Markdown+JSON report
  under `output/data-gap/`. **Full coverage includes macro/FRED/rates/gold**
  (healed by re-running their idempotent ingest jobs over a lookback window).
  A nightly job (`DATA_GAP_HEALER_ENABLED`, default off) runs at 20:00 ET — just
  after the UW quota reset — under an advisory lock, capping **only** UW spend
  (`DATA_GAP_HEALER_MAX_UW_CALLS`, default 20000); Massive/external are
  uncapped. `/api/health` gains a `gap_healer` block. Policy matrix:
  `docs/runbooks/data-gap-dataset-policy.md`; runbook:
  `docs/runbooks/data-gap-healer.md`.
- **YTD historical backfill from UW (`/volatility/stats`, `/volatility/realized`).**
  `realized_volatility_history` + `volatility_stats_history` are UW-sourced, not
  derived — repointed off the rollup adapter (which only writes
  `vrp_daily`/`stock_analytics_daily`) to dedicated heal adapters:
  `realized_volatility` (full ~1y series, 1 call/ticker) and `volatility_stats`
  (one row per ticker/date via `?date=`, the YTD `vol_stats` backfill — that
  table only accumulated forward from its 2026-05-11 inception because the
  fetcher was current-snapshot-only). `fetch_volatility_stats` gains an optional
  `market_date` selector (current-snapshot default preserved).
- **Watchlist ticker lifecycle log** (`migration 093`,
  `watchlist_ticker_events`). `reconcile_watchlist_lifecycle` (run nightly + CLI
  `reconcile`) diffs the live watchlist vs the last-known state: **added/re-added**
  tickers are logged and backfilled by the same run's audit; **removed** tickers
  are logged with their rows left intact (no exclusion code needed — the
  denominator is the live watchlist, so they already drop out). Append-only, so a
  remove→re-add cycle keeps the full history.
- **Benchmark snapshots persist through a heartbeat clock race.**
  `scheduler_heartbeat_lag_seconds` is clamped to `max(0, …)` in
  `benchmark/collector.py` so a heartbeat landing a hair after `now_utc` no
  longer violates the `058` `>= 0` CHECK and drops the snapshot
  (`pipeline_benchmark_snapshots` was stuck at 0 rows).

### Fixed

- **Gap-healer trading-day calendar (kills weekend/holiday phantom gaps).**
  `_calendar_dates` unioned the dataset's own dates with the `market_tide`
  reference, so a stray weekend/holiday price-bar in a dataset leaked that
  non-trading day into its own expected calendar — manufacturing a full-watchlist
  phantom gap for every ticker missing that bar. The reference
  (`market_tide_sentiment_daily`) is a clean trading-day spine (0 weekend/holiday
  rows), so it is now the sole calendar. On real prod data this cut the gap count
  25,814 → 15,021; `vrp_daily`/`realized_volatility_history`/`stock_analytics_daily`
  collapsed from ~3,000–3,800 phantom gaps each to the 2 genuine misses each.
- **Resume recovers items orphaned by a killed run.** A timed-out/killed run left
  items stuck `running`, which `claim_next_items` skips; `resume` now requeues
  them to `planned` first (heals are idempotent, so a blanket requeue is safe),
  so a backfill actually continues where it left off.

## [0.4.1] — 2026-06-30

### Changed

- **Market Tide spot overlay uses xenon IB bars as the primary source** (Apex
  REST is the automatic fallback). `sources/apex.py` now tries
  `POST /historical/bars` against xenon's query API (`XENON_QUERY_API_URL` /
  `XENON_QUERY_API_KEY`) before falling back to the Apex lake endpoint. Requires
  xenon ≥ v0.7.3 (moremeds/xenon#169 — fixes `_bar_date_to_iso` truncating
  intraday timestamps to date-only).

## [0.4.0] — 2026-06-30

### Added

- **Market Tide tab — Top Net Impact chart with per-update rank change.** New
  panel beside the daily tide (UW `/market/top-net-impact`): horizontal diverging
  bars of market-wide net option premium (`net_call − net_put`) per ticker,
  bullish/bearish split. Each capture carries `prev_rank` into the next so the
  chart shows ▲/▼/• rank movement between updates. Captured every 15 min RTH
  (`regime_top_net_impact_scan`, uw-0, kill switch `TOP_NET_IMPACT_CAPTURE_ENABLED`);
  migration `090`; storage `top_net_impact_repository.py`; endpoint
  `/api/regime/top-net-impact`.
- **Tide slope/sentiment ("TIDE SENTIMENT").** Quantifies the UW Daily Market
  Tide guide: spread `S = NCP − NPP`, its session + 30-min slope, divergence
  (`trend_strength = |net displacement| / range`), driver (call/put buying/selling),
  momentum, and net-volume confirmation. Surfaced live on `/api/regime/market-tide`
  (`sentiment` block) + a banner in the tab. EOD-persisted per session for
  backtesting (`market_tide_sentiment_daily`, migration `091`; nightly
  `market_tide_sentiment_eod` @16:25 ET). `reports/market_tide_sentiment.py`.
  `macmini-prod.sh` seeds the full stored-bar history once at deploy time
  (`market_tide_sentiment_backfill.py --if-empty`, best-effort, no UW budget),
  so the backtest dataset is complete the moment the feature ships; later
  deploys skip it (seeds only when the table is empty).
  Forward-return probe (`scripts/research/tide_slope_backtest.py`,
  `docs/research/tide-slope/`) finds it **descriptive, not predictive** at the
  daily horizon (n=120 YTD: ~50% hit, |corr| below the significance bar).
- **Apex SPY-spot overlay for the tide chart.** `sources/apex.py` reads SPY 5-min
  closes from the Apex bars API; `scripts/backfill/market_tide_spot_backfill.py`
  joins them onto `market_tide_snapshots.spot` by UTC instant so the historical
  SPY gold line renders (UW tide carries no price).

### Changed

- **Market Tide tab redesigned + default regime tab.** Daily chart now follows
  the UW layout — compact stats line (`SPY · Vol · NPP · NCP`), `Net Premiums` /
  `Net Volume` band labels, SPY on the left axis, premium + baseline-0 volume on
  the right, date-first time axis — wrapped (with Top Net Impact) in a single
  titled container carrying the UW guide tooltip. Clicking **Regime** now defaults
  to **Market Tide** (was Gamma Exposure).
- **`market-tide` / `top-net-impact` fetchers treat UW 422 (future EST date) as
  no-data**, like 400 — so a backfill walking from "today" (still future in ET)
  skips cleanly instead of crashing.
- **VRP macro entry-capture now stores IB's native option greeks as the primary
  source.** `xenon_query.fetch_ib_option_quote` previously discarded the
  delta/gamma/vega/theta in the `/options/greeks` response and `quote_leg` always
  BS-computed greeks from the marked IV. The IB-native greeks (which reflect IB's
  live surface) are now consumed as primary, rescaled to argon's BS column
  convention — vega ×100 (IB per-1% vol → per-100%) and theta ×365 (IB per-day →
  per-year); delta/gamma already match. BS-from-IV remains the backup when IB
  returns no greek set (UW-fallback legs, or IB without greeks). Adds `'ib'` to
  the `greeks_source` tag (`VrpMacroEntryLeg.greeks_source` contract widened to
  `ib | bs | none`).

## [0.3.6] — 2026-06-25

### Fixed

- **Macro short-vol "Tracked entry" showed fabricated strikes/mids.** Pre-birth
  (no cohort captured today), the entry preview fell back to `_bs_indicative_legs`
  — a synthetic 5-pt SPX strike grid (e.g. 7095/7090, which aren't listed strikes)
  priced with flat-vol Black-Scholes, rendered in the card as if they were market
  quotes. A fake number is worse than none. Removed the synthetic path entirely:
  the `/vrp-macro-signal/entry/preview` endpoint now serves persisted-cohort legs
  (real strikes + NBBO) or **empty legs** with no fabricated ETD — the card shows
  "No entry preview yet" / "ETD —" until a real cohort exists. Pairs with the
  grid-cache fix below, which is what lets a real cohort actually get born.

- **VRP macro entry-capture never persisted** — the daily SPX auto-birth
  (`_birth_auto`) enumerated the listed strike grid via two live UW calls inside
  the 10:00–15:00 ET birth crons, but the UW daily quota is reliably exhausted by
  ~08:00 ET, so every birth 429'd and aborted (`vrp_macro_entry` /
  `vrp_macro_entry_quote` stayed empty; the preview card silently fell back to the
  BS-`modeled` indicative legs). Added a nightly `vrp_macro_entry_grid_refresh`
  job (03:50 ET, massive-0, when the UW budget is fresh) that caches the real
  UW-listed expiry + put strikes into a new `vrp_macro_entry_grid` table
  (migration 088). The unattended auto-birth now reads that cache and makes **zero
  UW calls**, so an exhausted daily quota can no longer abort it; the on-demand
  Capture button reads the same cache (UW-free whenever the cache is warm, i.e.
  after the first nightly refresh — a cold-cache click still falls back to a live
  UW lookup). The cache read reuses the most-recent prior day's real grid (within
  a 4-day staleness bound, chosen expiry still open) if a nightly refresh is
  missed, rather than skipping birth. As part of this, `_uw_chain_strikes` now
  closes its `scan_runs` row as `failed` on a UW error instead of leaving it stuck
  in `running` (the visible side-symptom of the original bug).

## [0.3.5] — 2026-06-25

### Fixed

- **#180 — `option_intraday_buckets` covered only ~half the watchlist.** The
  intraday OI-mover refresh is registered on the primary UW worker only, but it
  still passed the per-worker crc32 shard filter — so ~55 shard-1 tickers
  (TSLA/NVDA/MSFT/GOOGL/META/AVGO …) were fetched by nobody and their stock-page
  TAPE column stayed permanently blank. The job now covers the full watchlist
  (`ticker_filter=None`; single-flight is already enforced by its advisory
  lock), and emits per-outcome counters (`skipped_no_run`, `skipped_no_movers`,
  `contracts_empty`, `contracts_error`) so a future coverage gap self-reports.
  One-shot backfill: `scripts/backfill/intraday_buckets_backfill.py`
  (budget-gated) — `--missing` auto-targets the blank set, and `--since` sweeps
  the full per-session history (`backfill_intraday_history`, distinct advisory
  lock) bounded by our recorded `oi_change_events` sessions, not just the latest
  run. Roughly doubles this job's daily UW calls; `UwClient` throttle/retry
  absorbs transient 429s.
- **#179 — single-name `greek_exposure_daily` froze at 2026-05-20.** It is
  index-only by design (the regime GEX scan only covers `gex_scan_tickers`); the
  100 single-name rows were a one-off backfill tail with no recurring writer. A
  new nightly job (`greek_exposure_daily_refresh`, 18:30 ET, uw-0) fetches UW's
  aggregate `/greek-exposure` history per single-name ticker — the SAME
  authoritative basis the indices use. (A DB→DB per-strike sum was tried first
  but validation showed it 20–134% off the aggregate — a partial-chain proxy —
  so it was dropped.) Backfill:
  `scripts/backfill/greek_exposure_daily_refresh_backfill.py` (UW, `--confirm`).

### Added

- **Data-date freshness monitor (prevention).** A nightly job
  (`data_freshness_monitor`, 21:00 ET) records, per curated per-ticker table,
  the newest **data date** + scope-aware active-watchlist coverage into
  `data_freshness_snapshots`, flags freezes, WARN-logs, and surfaces a
  `freshness` block on `/api/health` (all DB-up returns). Complements
  `list_record_health`, which keys on write-timestamps and skips no-timestamp
  tables (e.g. `greek_exposure_daily`) — the blind spot that let the vrp/greek
  freezes slip for five weeks. Migration `087`.

## [0.3.4] — 2026-06-25

### Fixed

- **`vrp_daily` silently froze for ~90% of the watchlist** (2026-05-22 onward).
  UW's realized-volatility endpoint began returning `null` for the
  `realized_volatility` column while `price` + `implied_volatility` stayed fresh;
  the nightly `nightly_vol_analytics_rollup` fed the raw null RV into
  `compute_vrp_series`, so `vrp = iv − rv` was `NaN` and `persist_vrp_daily`
  wrote nothing (the same loop's RV-independent `stock_analytics_daily` kept
  updating, masking the gap). The rollup now applies `_fill_rv_from_price` —
  deriving RV from the fresh price column, the same convention the stock-page
  read path already used — before computing VRP. Added
  `scripts/backfill_vrp_daily.py` (pure DB→DB, zero UW calls, idempotent) to
  recover the historical gap; one run restored `vrp_daily` from 9 → 104/104
  active tickers fresh. Regression test added in
  `tests/integration/worker/test_volatility_jobs.py`.

## [0.3.3] — 2026-06-24

### Added

- Per-stock **Short-Vol card** on the stock page's Market Structure tab — the
  single-name sibling of the SPX Macro Short-Vol card, placed third on the
  Directional-Bias row. A TRADE/SKIP sell-premium readout derived at read time from
  the latest persisted `vrp_daily` row (no new endpoint, job, or migration): TRADE
  only when vol is rich (`vrp_z_20 ≥ 1.0`), the ticker's sector is in the sellable
  set (`vrp_gate`), and a known next-earnings date is clear of the ~45-day hold
  window; otherwise SKIP with a reason (`vol not rich` / `sector vol not sellable` /
  `earnings inside hold window` / `earnings date unavailable`). On TRADE it models the
  same flat-vol bull put spread (0.25Δ short / 0.125Δ wing, ~30-day hold) as the macro
  signal, reusing `size_weight` + `build_bull_put_spread`; macro/ETF classes skip the
  earnings gate (they don't report), mirroring `vrp_gate`'s asset-class split.
  Non-finite `vrp_z_20` (short-history NaN) is normalized away, and the build is
  wrapped so the card can never take down the stock page. New
  `reports/stock_short_vol.py`, `StockShortVol` model + `SingleStockReport.short_vol`,
  and `web/components/stock/panels/ShortVolPanel.tsx`. EOD basis (modeled off the
  EOD-close spot). Plan `docs/superpowers/plans/2026-06-24-stock-short-vol-card.md`.

## [0.3.2] — 2026-06-24

### Added

- VRP macro **forward entry-capture & markout recorder**: records the real forward
  NBBO + greeks of the SPX bull-put-spread the Macro Short-Vol signal would place,
  tracked daily to expiry. A daily-born `auto` cohort (the 4 put contracts bracketing
  the 0.25Δ short / 0.125Δ wing at ~43-cal-DTE) is snapshotted **8×/day** (10:00–15:00
  ET hourly + 15:55 EOD + 16:10 post-close), tapering to EOD-only after 30 calendar
  days. Each leg quotes **xenon/IB-primary** (true NBBO + IV) → **UW fallback** →
  **greeks always BS-computed** from the marked IV (one-model: IB theta is per-day, BS
  per-year — never mixed). New table pair (`vrp_macro_entry` + `vrp_macro_entry_quote`,
  migration `085`), `reports/vrp_macro_entry.py`, `worker/jobs/vrp_macro_entry.py`
  (massive-0, gated by `vrp_macro_entry_capture_enabled`), and
  `GET/POST /api/regime/vrp-macro-signal/entry/{preview,capture}`. The Macro Short-Vol
  regime card gains a strike/ETD preview panel (served from the persisted snapshot —
  zero IB, zero new UW) + a one-click Capture button; the "(gate at 0)" / "stand aside"
  copy is dropped. Live-verified against prod IB (3/4 legs `source=xenon_ib`). Also
  fixes the stale `xenon_query_api_url` default (`:8421`, which was dead → silently
  no-op'd the surface IV canary too) to the mini's authenticated `:8321`; deploy must
  set `XENON_QUERY_API_KEY` in the mini's argon `.env` or the IB path falls back to UW.
  Plan `docs/superpowers/plans/2026-06-24-vrp-macro-entry-capture.md`.
- GOAS put-write delta sweep (research): a self-contained study finding the short-put
  **delta + tenor sweet spot** for the Goldman Options Advisory Strategy (systematic
  always-on OTM index put-writing). Three new `reports/` modules —
  `goas_putwrite_pricing.py` (a parametric downside-skew layer `iv(K)=atm·(1−slope·ln(K/S))`
  calibrated to GOAS's one published quote: 2026-05-05 SPY 96.2%-strike / 0.700%-premium →
  slope 2.693, with flat-vol as the conservative floor), `goas_putwrite_account.py` (a
  laddered, defined-risk **cash-secured** put-write NAV book — held to expiry, intrinsic
  settlement, fair-value daily marks, collateral earning the risk-free per CBOE PUT-index
  convention — plus `curve_metrics`/`putwrite_metrics` and a SPY buy-hold benchmark), and
  `goas_putwrite_sweep.py` (delta×tenor×pricing×fee sweep with regime slices and a
  per-regime catastrophe-gated ranking; management fee modeled as a downstream NAV drag,
  copying GOAS's own fee framing). Runner `scripts/research/goas_putwrite_run.py` reads SPY+VIX
  daily closes directly from the market-warehouse lake (2006→, ~20.4y, no Postgres/network)
  and writes five full-trace artifacts + a master findings note under
  `docs/research/goas-putwrite/`. Headlines: gross Sharpe rises monotonically with delta but
  short (21d) weekly writing fails catastrophically in fast crashes (COVID Sharpe −1.6) — the
  binding constraint is **tenor, not delta**; net-of-1%-fee gated sweet spot is **0.30Δ/63d**
  (Sharpe 0.147), conservative pick **0.15Δ/63d** (Sharpe 0.108, maxDD −14%, 95% win-rate).
  Every unlevered cash-secured cell trails SPY buy-hold risk-adjusted (best 0.15 vs 0.34) but
  at 2–4× smaller drawdown — the premium harvest above cash is only ~0.5–1.4%/yr, so GOAS's
  3–6% net target requires the 20–40% leverage this defined-risk study excludes. Reproduce:
  `uv run python scripts/research/goas_putwrite_run.py`.

## [0.3.1] — 2026-06-23

### Added

- VRP backtest iteration 4 (research): robustness suite on the SPX macro short-vol
  WINNER — `reports/vrp_robustness.py` (min viable capital, SPY buy-and-hold benchmark,
  geometric compounding metrics, weekday sweep, bear-start study, and a seeded
  Monte-Carlo suite: entry-timing jitter, stationary block bootstrap, randomized
  start incl. a GFC-windowed variant, config perturbation) plus six backward-compatible
  flags on the `vrp_capital_account` ledger (compounding, entry-weekday, entry-jitter,
  staggered extra tranche) that reconcile byte-for-byte to the iteration-3 path when off.
  Runner `scripts/research/vrp_robustness_run.py` writes seven `iter4-*.csv` full traces
  (per-config + per-trial Monte-Carlo + long-form bear-start equity path); findings in
  `docs/research/vrp/vrp-backtest-iteration-4-findings.ipynb` + an Iteration-4 section of
  the master report. Every experiment benchmarked against the iteration-3 SPX base case
  and SPY buy-and-hold. Headlines: the staggered extra tranche marginally beats the base
  (Sharpe 1.71 vs 1.68) while the contract overlay is exposure-not-edge; entry weekday
  matters modestly (1.33–1.53, all below the 1.65 stride); starting at a bear top still
  earns +150–180% over 36m; and config-perturbation p5 Sharpe 1.05 shows the result is
  not a knife-edge overfit. SPX vol-selling is six-figure-capital (one spread's max-loss
  rises ~15× to ~$28k by 2026).
- VRP capital-utilisation backtest (research): new `reports/vrp_capital_account.py`
  — a single shared **$50k cash-account ledger** (`CapitalConfig`,
  `desired_contracts`, `simulate_account`, `account_metrics`) that _reuses_ the
  validated macro short-vol `WINNER` engine to measure annualised return, capital
  utilisation, skip/fill rates, Sharpe and max-drawdown on a real dollar account
  (integer contracts floored to a risk-% of capital, capital-capped with logged
  skips). Reconciles exactly with `backtest_laddered` (Δ Sharpe 0.000). Adds SPY
  to macro `INDEX_SPECS`, a sweep runner (`scripts/research/vrp_capital_sweep.py`)
  with full-trace CSVs, and an executed findings notebook + verdict/master report
  under `docs/research/vrp/` (single-name SPX beats the 3-name blend; the overlay
  is leverage not edge; compounding sweet spot ≈ stop at 4–8×). New `research`
  dependency group (matplotlib/nbconvert/ipykernel) for the notebook only.
- Option-surface historical backfill: `option_surface_backfill` function and
  `scripts/option_surface_backfill.py` runner seed `option_surface_grid_daily`
  for up to 30 past trading days in one shot. UW `/greek-exposure/expiry` and
  `/greeks` both accept an optional `date=` param (now forwarded by the fetchers);
  dates already in the table are skipped. Run promptly after first deploy — UW
  403s beyond ~30 trading days.

### Fixed

- `reports/vrp_macro_drawdown._lake_spot` now skips lake rows with a null
  `trade_date`. SPY's equity-lake parquet carries ~73% null-date rows (an
  alternate-schema partition); without the guard `load_index_vol("SPY")` raised
  `TypeError` on the `d >= start` comparison. No-op for symbols with clean dates
  (QQQ/IWM).

## [0.3.0] — 2026-06-23

### Added

- Option-surface capture: a nightly, forward-accumulating per-strike IV/greeks
  grid for every watchlist ticker (`option_surface_grid_daily`, migration 077),
  plus an ATM IB-vs-UW IV canary (`iv_source_validation`, migration 078). New
  `option_surface_capture` job (19:00 ET) and `option_surface_iv_canary` job
  (19:30 ET) on the uw-0 worker, Mon–Fri. Enumerates the full term structure via
  `greek-exposure/expiry` — not `/option-contracts`, which UW silently caps at
  500 contracts by volume and so drops long-dated expiries (measured: SPX 28/53
  missing). One `/greeks` call per expiry, idempotent upsert, per-ticker failure
  isolation. The surface only accrues forward: UW returns 403 for per-strike
  history beyond ~30 trading days, so every uncaptured night is permanently lost.

## [0.2.3] — 2026-06-22

### Fixed

- Release pipeline no longer wedges the mac-mini auto-deploy on `uv.lock` drift.
  `cut.sh prepare` now re-locks `uv.lock` so its editable self-version tracks the
  version bump and commits it with the release, and `version_sync_check` (run via
  system `python3` before `uv sync` in CI, so a stale committed lock can't be
  auto-repaired and hidden) fails the build if the lock self-version ever drifts
  from `VERSION` again. Previously the committed lock lagged the bump; the first
  `uv run` on any host rewrote that one line, dirtied the tree, and the deploy
  poller refused every deploy — silently pinning prod to the last-deployed
  release (the mini sat on v0.1.2 for 4 days while v0.2.0–v0.2.2 published).

## [0.2.2] — 2026-06-22

### Added

- VRP macro signal deploy slice: nightly persistence + read API for the promoted bull-put-spread signal shipped in 0.2.1. New `vrp_macro_signal_daily` table (migration 083), `vrp_macro_signal_refresh` job (03:45 ET, Mon–Fri, primary worker — runs SPX/QQQ/IWM weekly readout + `backtest_laddered` headline and persists one row per name per snapshot date, with per-name failure isolation), and `GET /api/regime/vrp-macro-signal` returning the latest signal per name. Closes the persist-every-research-trace gap for the VRP macro engine.

## [0.2.1] — 2026-06-22

### Added

- VRP macro signal engine (`reports/vrp_macro_signal.py`): promoted bull-put-spread winner config (Δ0.25 short, ramp+ vrp-z sizing, 30 trd-day hold) into first-class engine code with `WINNER` constant, `backtest_laddered` (SPX Sharpe 1.65 / QQQ OOS 1.00), and `current_macro_signal` weekly readout (TRADE/SKIP + modeled strikes/credit/max-loss)
- VRP macro research expansion (`reports/vrp_{candidates,backtest,directional,harvest_axes,gate,rv_validation}.py`): corrected-measurement engine, sector/horizon/directional/ΔVRP sweep axes, per-ticker iron-condor candidates, paper ledger, model-repriced weekly backtest
- Corporate actions refresh job (nightly 17:35 ET) for exact-RV split/dividend adjustment

## [0.2.0] — 2026-06-21

### Added

- VRP harvest markout (`reports/vrp_markout.py`, migration `079_vrp_harvest_verdicts`,
  `GET /api/regime/vrp-harvest`): scores whether selling rich vol (`vrp_z ≥ +1`) earns a
  reliable, positive premium per `(asset_class, deviation_class)` bucket. Reuses the skew
  engine's out-of-sample discipline — time-ordered walk-forward holdout plus a per-quarter
  catastrophic-degradation gate — over the existing `vrp_daily` panel, and excludes any
  forward window spanning a (flow-event-reconstructed) earnings date. Verdicts
  (`HARVEST_SELLABLE` / `NONE`) persist nightly at 18:50 ET (massive-0 worker) to
  `vrp_harvest_verdicts`; the RICH−CHEAP spread is recorded so a flat (no-edge) result
  stays legible.

## [0.1.2] — 2026-06-18

### Fixed

- Stock detail pages (Flow / Market Structure / GEX) no longer render empty
  during US off-hours. `Repository.latest_run_id` selected the newest scan_run
  via a hand-maintained `notes` denylist; the skew engine's `skew_swing_greeks`
  side-channel runs were not on it and — having higher run_ids and no aggregates
  — shadowed the real `full_scan`, blanking every ticker's detail page after
  ~17:30 ET each day. The selector (and the `get_scan_duration_summary` health
  metric) now key on the property the report actually needs —
  `status='ok' AND aggregates IS NOT NULL` — so no future side-channel job can
  re-break it. No data was lost; the fix is read-path only.

## [0.1.1] — 2026-06-17

### Added

- Health sidebar now shows deployed backend version in the collapsed header,
  sourced from the running process via the existing `/api/health` poll.

## [0.1.0] — 2026-06-17

### Added

- Baseline release. Per-ticker options analytics: Next.js web (`web/`, :3001),
  FastAPI read API (`src/uw_scan/api/`, :8400), and the APScheduler worker, over
  a single Postgres (`uw_scan` schema). Scanner, regime (CRI/GEX/VCG), skew,
  Gold Compass, cockpit, and Trade Insights AI (Codex/Claude/DeepSeek) ship in
  this baseline. First release cut through the tag-driven `release.yml` pipeline.
