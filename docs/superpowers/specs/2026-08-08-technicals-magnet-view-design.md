# Technicals "Magnet View" sub-tab — design

**Date:** 2026-08-08
**Status:** design approved, research not started
**Scope:** one new sub-tab inside the stock Technicals tab, gated behind a blocking research phase

---

## 1. Motivation

A third-party chart poster ("Balder's Fable Picks") compresses six unrelated data
surfaces into one glance, with every number carrying a stated _role_ ("supply —
break-UP trigger"). That compression is the thing worth taking. Its forecasting
content is not.

### 1.1 What the reference actually does

Decoded from two sample charts (MU, TSLA), nine layers:

| #   | Layer            | Method                                                                 | Type              |
| --- | ---------------- | ---------------------------------------------------------------------- | ----------------- |
| 1   | Swing pivots     | ZigZag; `A` = last confirmed high, `B` = last confirmed low            | geometry          |
| 2   | S/R              | `RESISTANCE = A`, `SUPPORT = B` — the pivots themselves, no clustering | geometry          |
| 3   | Measured move    | `STRETCH = R + 0.618·(R−S)`, `DOWN = S − 0.618·(R−S)`                  | geometry          |
| 4   | Leg state        | state machine on (direction of last pivot, price vs R/S)               | geometry          |
| 5   | Magnet profile   | volume-at-price as a sideways dot cloud; ★ = POC                       | empirical         |
| 6   | Kinematics       | 1st/2nd derivative of price → ACCEL/DECEL                              | empirical         |
| 7   | Vol context      | ATM IV + 5d change; BB(20,2σ) width percentile regime                  | empirical         |
| 8   | Pattern registry | double-bottom / double-top confidence 0–1; named patterns              | scored heuristic  |
| 9   | THE READ         | template interpolation, one bullet per fired condition                 | string formatting |

Layer 3 was verified exact against both samples:

- MU: `990.21 + 0.618 × 251.21 = 1145.46` ✓ and `739.00 − 0.618 × 251.21 = 583.75` ✓
- TSLA: `407.76 + 0.618 × 109.44 = 475.39` ✓ and `298.32 − 0.618 × 109.44 = 230.69` ✓

### 1.2 Its forward content

Two distinct objects:

- **A fan** — three dashed splines from `LAST` to STRETCH / RESISTANCE / DOWN.
  Geometrically a fan chart, but drawn to hit levels already computed by layer 3.
  No distribution, no width, no probability. The chart's own footer disclaims it:
  _"scenario paths are illustrative, not forecasts."_
- **One genuine conditional** — TSLA only: _"Bollinger bands at their widest
  decile … these regimes have leaned higher over the following week."_ Stated
  with no sample size, no dispersion, no hold-out.

**Design consequence:** argon replaces the decorative fan with a real forward
density. The rendering primitive for that already exists.

### 1.3 The hidden fragility

Layers 1–4 are one idea — pick two points, do arithmetic — and everything
downstream inherits it. Change the ZigZag reversal threshold and every level,
every distance %, and every sentence in THE READ changes. The reference never
shows that threshold anywhere on the chart. This spec treats it as a swept
parameter, not a constant chosen by eye.

---

## 2. Non-goals

- Not a replacement for the existing Technicals charts. The new view is a
  **separate sub-tab**; overlap with existing panels is expected and accepted.
- Not an AI-written read. Argon already runs three AI providers on the Trade
  Insights tab. This read is a deterministic template — free, reproducible,
  zero-latency.
- Not a 21-day cone. Withheld on sample grounds (§3.3).
- Not the reference's pattern registry (layer 8). Deferred; nothing depends on it.
- Not a trade surface. Display and context only. No order path, no sizing.

---

## 3. Phase 1 — blocking research

No UI work begins until this completes. One script,
`scripts/research/magnet_cone_calibration.py`, two experiments sharing one data load.

### 3.1 Data sources

| Input                        | Source                      | Note                                                                     |
| ---------------------------- | --------------------------- | ------------------------------------------------------------------------ |
| ATM IV per (ticker, session) | `option_surface_grid_daily` | via the `load_atm_iv` pattern in `storage/theta_harvester_repository.py` |
| Daily closes / OHLC          | `daily_ohlc`                | forward realisations and ATR                                             |

**Hard constraint: do not read `iv_rank_history`.** It carries only ~4 tickers per
session. The obvious `market_date <= as_of ORDER BY DESC LIMIT 1` lookup silently
returns months-old IV — on 2026-07-24, of 114 grid tickers, 3 had same-day IV, 85
were stale by more than a week, and 26 had never been captured. That failure mode
passes every type check and would compare May's IV against July's realised vol,
destroying the calibration silently. `option_surface_grid_daily` had 114/114
coverage the same session. This trap is already documented in
`theta_harvester_repository.load_atm_iv`; the research must reuse that path, not
re-derive it.

### 3.2 E1 — cone calibration

Under Black–Scholes with `r = q = 0`, `ln(S_T/S_0) ~ N(−σ²T/2, σ²T)` where
`T = h/252`. So the standardised residual is

```
z = [ ln(S_{t+h}/S_t) + σ²T/2 ] / ( σ·√T )        z ~ N(0,1) under the model
```

Computed per (ticker, session, horizon). Reported:

- **Coverage** at `|z| < 1` and `|z| < 1.96` against nominal **68.3% / 95.0%**
  (95.4% is the `|z| < 2` figure — pairing it with 1.96 would manufacture a
  spurious 0.4pt miscalibration out of nothing)
- **PIT** — `u = Φ(z)`, histogram plus KS test against Uniform(0,1)
  (Diebold–Gunther–Tay 1998)
- **Scale** `k = std(z)`, expected `< 1` if a variance risk premium is present,
  reported alongside a MAD-based robust estimate — a plain standard deviation
  over fat-tailed returns is precisely the estimator not to trust alone
- **Location** `mean(z)`, reported as a **diagnostic only**

#### Fit scale, never drift

The cone is a _risk-neutral_ density tested against _physical_ realisations, so
`z` is biased on two axes: the equity risk premium shifts its mean, and the
variance risk premium shrinks its spread. Only the second is correctable here.

Estimating drift from 161 trading days is hopeless — at 40% annualised vol the
standard error on annualised drift is roughly `0.40 / √(161/252) ≈ 50%`, larger
than any drift being estimated. Variance converges in days; drift needs decades.
**The calibration fits `k` (scale) only.** `mean(z)` is published as a diagnostic
and never used to shift the cone.

#### Overlapping-sample treatment

At `h = 5` with daily sampling, consecutive observations share 4 of 5 days.
Overlap does not bias coverage point estimates, but it destroys the independence
that p-values and confidence intervals assume.

- Coverage and `k` point estimates: computed on the full overlapping sample
- **All p-values and CIs (including the KS test): non-overlapping subsamples or a
  moving-block bootstrap.** A KS p-value computed on overlapping data is
  meaningless and must not appear in the output.

#### Pooling and validation

Fit pooled, per-sector, and per-ticker. Walk-forward OOS through
`src/uw_scan/backtest/` — fit `k` on the front window, validate coverage on the
held-out tail.

**Per-ticker `k` earns a table only if its cross-sectional dispersion exceeds OOS
error.** Otherwise a single pooled constant ships: no migration, no refit job.
Single-name vol sellability is known to vary by sector in this repo, so dispersion
is plausible — but that is a measurement, not an assumption to build around.

Tickers with fewer than **100 usable overlapping observations at the horizon**
(≈64% of the 156 possible at 5d) are excluded from the fit, and the exclusion
list is published alongside the results. The threshold exists because a ticker
with sparse surface coverage contributes a `k` estimate dominated by noise while
still carrying full weight in a pooled average.

### 3.3 Sample budget

Surface history spans 2025-12-26 → 2026-08-08 ≈ **161 trading days**:

| Horizon | Overlapping obs/ticker | Non-overlapping | Status       |
| ------- | ---------------------- | --------------- | ------------ |
| 5d      | 156                    | 31              | ship         |
| 10d     | 151                    | 15              | ship         |
| 21d     | 140                    | **6**           | **withheld** |

Six independent windows per ticker has no power. Cross-sectional pooling helps
but watchlist tickers share a common volatility factor, so effective sample size
is far below `n_tickers × 6`. 21d is revisited once the surface accrues; it
accrues forward-only, so this resolves with time and no backfill is possible.

### 3.4 E2 — 0.618 first-passage and ZigZag sweep

For `k_atr ∈ {2.0, 2.5, 3.0, 3.5, 4.0}` (reversal threshold in ATR(14) units):
from each confirmed rising leg, does price touch `R + 0.618·(R−S)` before losing
`S`, within 60 trading days? Outcomes: **hit / stop / neither**.

Scored against a **drift-matched null** — the same two barriers, simulated with
the ticker's own drift and realised volatility. Without that null the hit rate is
uninterpretable: a rising leg has upward drift baked into its definition, so a
high raw hit rate is expected under no edge at all.

This sweep also selects the `k_atr` used in production — by measured first-passage
performance, not by eye.

### 3.5 Persistence

Per the repo's standing research rule, the _full_ result set — every config
crossed with every metric, not the headline — is durable before the process exits:

- `docs/research/2026-08-08-magnet-cone-calibration/` — CSV traces plus a verdict
  note
- `backtest_sweep_runs` / `backtest_sweep_results` — the `k_atr` sweep, which is
  exactly what the generic sweep tables exist for
- The exact reproduce command (script path, args, seed) recorded in the note

### 3.6 Gates

| Gate                                                                | Outcome if failed                                                                                                                                                                        |
| ------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **G1** — some `k_atr` beats the drift-matched null OOS              | STRETCH/DOWN ship as unlabelled geometry; role text becomes "0.618 extension (no measured edge)"; the read drops its target sentences; the `+30.7%` headline framing is dropped entirely |
| **G2** — calibrated cone reaches nominal coverage OOS at 5d and 10d | that horizon is withheld from the view                                                                                                                                                   |
| **G3** — per-ticker `k` dispersion exceeds OOS error                | pooled constant ships instead; no table, no refit job                                                                                                                                    |

**G1 failing does not cancel the view.** Support/resistance, the magnet profile,
and the cone stand on their own; only the measured-move framing changes.

### 3.7 Implementation planning is two passes

This spec covers all three phases, but it does **not** map to a single
implementation plan. Phase 1's gates change what Phases 2–3 build: G1 decides
whether STRETCH/DOWN are targets or unlabelled geometry, G2 decides which
horizons the cone carries, G3 decides whether a per-ticker `k` table and refit
job exist at all.

So: **Plan A covers Phase 1 only.** Plan B (Phases 2–3) is written after the
gates resolve. Writing a detailed build plan now would mean planning against
three unknown branch points and rewriting most of it — and, worse, would create
pressure to interpret the research in whichever direction preserves the plan
already written.

---

## 4. Phase 2 — backend

New module `src/uw_scan/cards/magnets.py`. Deliberately not an extension of
`cards/technicals.py`, which is already large.

| Function                                 | Returns                                                   |
| ---------------------------------------- | --------------------------------------------------------- |
| `all_pivots(df, k)`                      | full ZigZag pivot list                                    |
| `magnet_levels(df, k)`                   | `R`, `S`, `stretch`, `down`, `sma20`, `last`, `leg_state` |
| `cone(spot, atm_iv, k_shrink, horizons)` | calibrated bands in price space                           |
| `build_read(levels, cone, ctx)`          | deterministic bullet list                                 |

`cards/technicals.py::last_pivot_index()` currently builds a full pivot list and
discards all but the last index. It becomes a one-line wrapper over `all_pivots`,
so its single existing caller (`cards/technicals.py:849`) is untouched and the
refactor is behaviour-preserving.

New endpoint `GET /stock/{ticker}/magnets`, separate from `/stock/{ticker}/technicals`
so the cost is paid only when the sub-tab is opened. Contract model in
`src/uw_scan/models/magnets.py`; `web/lib/types.ts` regenerated via
`npm run gen:types`.

---

## 5. Phase 3 — web

Sub-tab selection is **local state persisted to `localStorage` under
`technicals:view`** — the pattern `TechnicalsPriceChart.tsx` already uses for
`technicals:priceOverlayMode`, chanlun, and volume profile. No routing changes to
the `[tab]/` segment.

New components under `web/components/stock/tabs/technicals/`:
`MagnetSubTab.tsx` (composite), `MagnetChart.tsx`, `MagnetTable.tsx`,
`MagnetRead.tsx`.

Reuse, which is the point:

| Piece                            | Source                       | New code                                                                                                      |
| -------------------------------- | ---------------------------- | ------------------------------------------------------------------------------------------------------------- |
| BB(20,2σ)                        | `lib/lwc/bandsIndicator.ts`  | none                                                                                                          |
| Magnet profile (volume-at-price) | `lib/lwc/volumeProfile.ts`   | none                                                                                                          |
| Cone                             | `lib/lwc/densityProfile.ts`  | none — accepts price-space bars already; `components/regime/DensityConeChart.tsx` is the working reference    |
| Four sub-panel tiles             | `panels/Sparkline.tsx`       | ~40 lines each                                                                                                |
| Four level lines                 | `ISeriesApi.createPriceLine` | native lightweight-charts v5.2, already used at `TechnicalsPriceChart.tsx:635` and `DensityConeChart.tsx:310` |
| A/B pivot markers                | `createSeriesMarkers`        | native v5.2, already used at `TechnicalsPriceChart.tsx:8,528`                                                 |

Two rows above are superseded by §5.2: the volume profile and the cone both need
a **new render mode**, not zero new code. The primitives are reused; their
painting is not.

### 5.1 Visual fidelity is a requirement, not a preference

This sub-tab reproduces the reference's layout and chart style **deliberately and
closely**. It uses the reference's own palette rather than argon's CSS theme
tokens.

That is a documented, intentional deviation from house style. Without this note
someone will later "fix" the inconsistency and destroy the thing that makes the
view readable — the reference's colour coding is load-bearing, because every
level's colour is how you identify its role at a glance without reading the table.

Layout, top to bottom:

1. **Header** — `TICKER · STATE ↑ (description)` in large bold green; beneath it a
   pipe-separated grey subtitle: `state | RSI | bottom/top | sector 5d | IV +Δ5d`
2. **Main chart** — candles, SMA20, BB(20,2σ), ZigZag with A/B pivots, four level
   bands, and the right-edge projection zone
3. **Four tiles** — VOLUME · RSI 14 · MOMENTUM · ATM IV, each `label` left /
   `headline + Δ` right
4. **Bottom row** — magnet table left, THE READ right
5. **Footer** — italic grey legend and the scenario disclaimer

Palette (from the reference):

| Element      | Colour                   | Treatment                             |
| ------------ | ------------------------ | ------------------------------------- |
| STRETCH      | cyan                     | dashed line + translucent band        |
| RESISTANCE   | red / salmon             | solid line + translucent band         |
| LAST         | yellow                   | dashed line + filled label box        |
| SUPPORT      | green                    | solid line + translucent band         |
| DOWN         | amber                    | dashed line + translucent band        |
| SMA20        | lavender                 | solid ~2px                            |
| BB(20,2σ)    | pale lavender            | dotted, thin                          |
| ZigZag       | blue-violet              | dashed ~2px                           |
| Pivots       | red ▽ tops, green △ lows | hollow triangle markers               |
| A / B labels | blue-violet              | bold, above/below the last two pivots |

Level _bands_ rather than hairlines matter: the reference draws each level as a
translucent zone with a solid core, which reads as "an area price reacts to"
instead of a false-precision single price.

### 5.2 The right-edge composition

The reference's right edge is two stacked things, and the spec keeps them
separate because only one of them is a forecast:

**Magnet profile (volume-at-price — NOT a forecast).** Rendered as a jittered dot
cloud: red dots above spot (supply), green below (demand), gold for the last 15
sessions, a smooth envelope curve tracing the outer edge, and a ★ with a price
label at the heaviest shelf. `lib/lwc/volumeProfile.ts` currently paints bars, so
this adds a **dot-cloud render mode** to the existing primitive — the binning,
POC and value-area maths are untouched.

**Scenario paths + calibrated cone (the forecast).** Three dashed level-seeking
paths with right-edge text labels — green `bull path` → STRETCH, grey dotted
`base path` → RESISTANCE, red `bear path` → DOWN — drawn **on top of** the
calibrated IV cone from §3.2. A small new primitive handles the paths and their
labels.

This layering is the whole point of the view: his paths show where the geometry
points, the cone shows what the options market actually prices, and **their
disagreement is visible**. When a 0.618 target sits outside the calibrated 2σ
band, the chart says so without a word of prose.

The `history ← | → scenarios` divider caption and the `gold = last 15d` note are
kept verbatim — they are what make the right edge legible as projection rather
than data.

Jitter must be **deterministic** (seeded from price-bin index, not `Math.random`)
so the cloud does not shimmer on every re-render or pan.

---

## 6. Testing

**Python** — frozen real-ticker OHLC fixture: real prices captured once at
authoring time, hardcoded with an as-of date, no network at test time.

- `magnet_levels` reproduces the 0.618 arithmetic exactly
- leg-state transitions across a rising→falling pivot flip
- `last_pivot_index()` output is unchanged by the `all_pivots` refactor
- `cone` band edges at a known `(spot, σ, h, k)`

**Web** — vitest on the read-template builder and the level math only.
**No chart rendering under vitest**: lightweight-charts requires `matchMedia`,
which jsdom does not provide, and the component dies there.

---

## 7. Open risks

1. **Surface depth is the binding constraint.** 161 trading days caps every
   horizon. Only time fixes it — the grid accrues forward-only and UW's window
   does not permit backfill beyond what was captured.
2. **Cross-sectional correlation inflates apparent power.** Pooling 114 watchlist
   tickers does not give 114× the sample; they share a volatility factor, and the
   watchlist is concentrated in AI/semis. Effective `n` is materially lower than
   nominal, and block bootstrapping across tickers is the honest treatment.
3. **The 0.618 constant is unexamined folklore.** E2 tests it but does not test
   alternatives (0.5, 1.0, 1.618). If E2 shows edge, whether 0.618 specifically is
   load-bearing remains unknown and is out of scope here.
4. **Earnings are not handled.** ATM IV legitimately widens into a print, so the
   cone widens with it — arguably correct — but no earnings flag is surfaced on
   the view. Deferred.
5. **`k` is fit once and frozen.** If the variance risk premium regime shifts, the
   calibration decays with no monitor. A staleness check is deferred until the
   view has a live record.
