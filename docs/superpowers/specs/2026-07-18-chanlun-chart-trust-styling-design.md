# Chanlun chart trust-styling — design

**Date:** 2026-07-18 · **Status:** design (approved in brainstorm; spec under user review)
**Prior art:** `docs/research/2026-07-18-chanlun-trust-silver/` (the trust probe this
operationalizes) · `web/lib/chanlun.ts` (compute) · `web/components/stock/panels/TechnicalsPriceChart.tsx`
(lightweight-charts overlay).

## Problem

The trust probe established (on corporate-action-adjusted bars, 223 names, ~5.3y):

- **背离 (顶/底背离)** and **2/3 买卖点** never retract once confirmed; **1B/1S repaint
  24–34%** — untrustworthy even as annotations.
- Only 背离 carries a faint honest forward edge, and it is materially stronger when
  **trend-aligned**: a 底背离 **above** the 200-DMA / 顶背离 **below** it → 57% hit,
  +0.65% edge at 10 sessions (CI-positive, period-robust). The counter-trend subset is
  weaker.

The live Chanlun overlay draws every mark **uniformly** (divergences as one
`--accent-warm` circle marker; points as up/down arrows). The operator gets no visual
cue about which marks the research says to trust. This feature closes that gap —
purely by restyling existing markers.

## Goal

When the Chanlun overlay is on, make each mark's appearance reflect its trust tier —
client-side only, no backend, no new chart primitive, no new toggle.

## Scope

**In:**
- Emphasize trend-aligned 背离; dim counter-trend 背离.
- Dim 1B/1S points (repaint-prone).
- A one-line legend explaining the styling.

**Out (YAGNI for v1):**
- Validity-window level lines (needs a custom primitive like the 中枢 rects).
- A separate on/off toggle for the styling (always-on when the overlay is shown).
- Any backend / API / worker change. Any change to 笔/中枢/段 rendering.

## Design

### 1. Trend-agree computation (the one piece of new logic)

A pure helper in `web/lib/chanlun.ts`:

```ts
/** 200-SMA of closes; sma[i] = null until the window fills. */
export function sma(closes: number[], window: number): (number | null)[]

/** Per divergence: true if trend-aligned (底背离 above the 200-SMA / 顶背离 below),
 * false if counter-trend, null if the SMA is not yet defined at that bar. */
export function divergenceTrend(
  bars: ChanlunBar[],
  divergences: DivergenceMark[],
  window = 200,
): (boolean | null)[]
```

- Aligns each `DivergenceMark` to its bar by `time`; reads that bar's `close` vs the
  200-SMA at that index.
- **底背离 (bottom)** trend-agree ⇔ close ≥ SMA200; **顶背离 (top)** trend-agree ⇔
  close < SMA200.
- First 200 bars → SMA null → **unknown** (neutral rendering, never dimmed).
- **Honest nuance (documented in the legend + spec):** the chart flags at the
  divergence's **own bar**; the probe measured at the confirmation close ~8 bars later.
  In practice both sit in the same 200-DMA regime, so the visual cue matches the
  research subset; the chart is not claiming point-in-time-exact entry.

### 2. Visual treatment

lightweight-charts markers accept a per-marker `color` (rgba → opacity) and `size`.
The marker-building block in `TechnicalsPriceChart.tsx` (~lines 807–840) branches on the
trust tier. Opacity values are the design default; final constants live in the panel.

| Mark | Color | Rationale |
|---|---|---|
| 背离 trend-agree | `--accent-warm`, full opacity | the marks to trust (+0.65% subset) |
| 背离 counter-trend | `--accent-warm` @ ~0.35 alpha | weaker edge |
| 背离 unknown (early bars) | `--accent-warm` @ ~0.6 alpha | SMA undefined, don't over-claim |
| **1B / 1S** | positive/negative @ ~0.4 alpha | repaints 24–34% |
| 2B/3B, 2S/3S | positive/negative, unchanged | stable once confirmed |

Marker `text` stays as today (e.g. `底背离`, `1B?`); only color/opacity change.
The existing `?` (unconfirmed) suffix is orthogonal and preserved.

**Scope of the 1B/1S dimming:** applies to the **base 买卖点** (`chanlunGeo.points`) —
the level the probe measured. **段-level points** (`chanlunGeo.segPoints`, drawn at
`size: 2` with the `段` prefix) are a different level the probe did not test and are
**left unchanged** in v1. Same for 背离: only base `chanlunGeo.divergences` are
tiered (there is no separate seg-divergence marker today).

### 3. Legend

One compact line appended to the existing Chanlun legend block (`--text-muted`, same
style). The **canonical final copy lives in the plan** (Task 2 Step 6) — implement that
exact string; do not paraphrase:

> Marker emphasis = reliability, not entry timing: bright 顶/底背离 = trend-aligned
> (底 above / 顶 below the 200-DMA, the higher-conviction subset); faint 背离 =
> counter-trend or early; faint 1B/1S = repaint-prone (24–34%). Not a trade signal.

Without it the dimming is unexplained. Keep it terse; it is the only prose added.

## Testing

- **Vitest** (`web/tests/lib/chanlunTrend.test.ts`):
  - `sma` — pure numeric helper, tested on a known ramp series (no market data;
    asserts the null-warmup prefix and exact means).
  - `divergenceTrend` — a **pure index-vs-SMA alignment** function, tested with a small
    **hand-built** `ChanlunBar[]` + `DivergenceMark[]` whose close-vs-SMA relationships
    are known by construction (covering: warmup→null, bottom-above→true, bottom-below→
    false, top-below→true, top-above→false, unknown-time→null). This is a legitimate
    test double for a pure function — not fabricated market data. The real AAPL H1
    fixture is **not** usable here: it is 130 bars and produces **zero** divergences at
    any window (verified), so it cannot exercise the branches.
- `npm run typecheck` clean.
- `npm run build` clean.
- Manual/browser: load a stock page with the overlay on, confirm bright vs faint 背离
  and dimmed 1B/1S render, legend reads correctly. Screenshot under `output/playwright/`.

## What this can and cannot claim

- **Can:** direct the eye to the marks the research found more trustworthy, and flag the
  ones that repaint — making the overlay honest about its own reliability.
- **Cannot:** turn chanlun into a trade signal. The edge is a weak tilt (+0.65%,
  pre-cost, mega-cap-biased). The legend and spec say so; no sizing/entry guidance is
  implied by the styling.

### Known limitation — unadjusted 200-DMA near splits (verified 2026-07-18)

The trend split uses the **same 200-DMA the chart already plots** (the `sma200`
field behind the pink `SMA200` line) — verified identical to the client-rolled
`sma(closes, 200)` to the penny across every divergence on NVDA (0/23 flips) and
TSLA (0/17 flips), so the emphasis never contradicts the drawn line. But that
series is **not corporate-action adjusted**: for ~200 sessions after a stock
split the trailing window mixes unadjusted pre-split prices with post-split
prices, so the 200-DMA is corrupted (e.g. TSLA 2022-10-24 close 211.25 vs
"200-DMA" 732.11 after the Aug-2022 3:1 split; NVDA 2024-08-05 close 100.45 vs
593.64 after the Jun-2024 10:1 split). In that window the trend tier is
meaningless — but consistent with the equally-wrong pink line, and the trust
probe that justified this feature ran on adjusted **silver** bars where the
200-DMA is clean. This is the known livewire `adj_close` blocker surfacing on
the chart; it also corrupts the z-score and σ-band tiles, not just this styling.
The correct fix is upstream adjusted closes, **not** a client-side split
heuristic (fragile — legitimate large moves would misfire). Shipped as-is with
the legend disclosing it; away from splits (every recent view) the tier is
correct.

## Reused vs new

- **Reuse:** existing `computeChanlun`/`DivergenceMark`/`BuySellPoint`, the
  lightweight-charts marker path, `--accent-warm`/`--positive`/`--negative` tokens,
  `ChanlunBar`.
- **New:** `sma` + `divergenceTrend` helpers in `chanlun.ts` (+ unit test), the trust
  branch in the marker builder, the legend line.
- **No production data surface** — no migration, API, worker, or type-gen change.
