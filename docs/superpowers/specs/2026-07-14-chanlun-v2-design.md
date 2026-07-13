# Chanlun v2 — 线段 / 段级中枢 / 中枢升级 / 区间套 (design)

**Date**: 2026-07-14 · **Status**: approved · **Builds on**: Chanlun v1 (PR #277,
`web/lib/chanlun.ts` + `web/lib/lwc/chanlunZhongshu.ts` + toggle in
`TechnicalsPriceChart.tsx`; research: `docs/research/2026-07-14-chanlun-tv-view-research.md`)

## Goal

Complete the TradingView-style 缠论 chart view: add 线段 (segments),
段级中枢 + 段级买卖点, pragmatic 中枢升级 (zone merging), and weekly×daily
区间套 resonance. All client-side, same precedent as v1. The Python/alert
port stays deferred (separate workstream, not this spec).

## Out of scope

- 线段-recursion beyond one level (多级别联立 on the same timeframe)
- Textbook 九段升级 recursion (we ship a documented pragmatic merge instead)
- Intraday levels (argon has no intraday bar store)
- Python port / alert pipeline integration
- Any backend, API, or DB change — this is a pure `web/` feature

## 1. Algorithm layer

### 1.1 线段 — new module `web/lib/chanlunSeg.ts`

Feature-sequence (特征序列) method, **both termination cases**, ported from
the chan.py (`Vespa314/chan.py`, `seg_algo="chan"`) semantics. Input: the v1
stroke vertices (`BiVertex[]`). Output:

```ts
export type SegVertex = {
  time: string;
  price: number;
  kind: "top" | "bottom";
  confirmed: boolean; // false on the provisional tail, same contract as BiVertex
};
export function buildSegments(vertices: readonly BiVertex[]): SegVertex[];
```

Mechanics (exact reference pseudocode + hand-traced oracles are embedded in
the implementation plan):

- For an up-segment the feature sequence is its down-strokes (element high/low
  = stroke's price range); mirror for down-segments.
- Inclusion-merge feature elements direction-aware (same rule family as 包含处理).
- A fractal in the merged feature sequence proposes segment termination:
  - **Case 1** (no 缺口 between merged elements 1 and 2 of the fractal window):
    segment ends immediately at the fractal's stroke vertex.
  - **Case 2** (缺口): the end is provisional until the counter-direction move
    forms its own 3-stroke structure (its feature sequence produces a fractal);
    if the counter-move instead fails (price resumes beyond the extreme),
    the original segment continues and the candidate end is discarded.
- A segment spans ≥3 strokes; segments alternate direction and share
  endpoints with stroke vertices; the trailing segment is provisional
  (`confirmed: false`), consistent with v1's tail contract.
- Segment endpoints only ever sit ON stroke vertices — `SegVertex.time/price`
  are copied from the underlying `BiVertex`, never recomputed.

### 1.2 段级中枢 + 段级买卖点 — parametrize, don't duplicate

v1's pivot scan and BSP marking in `computeChanlun` operate on legs built
from `eps` (fractal endpoints). Refactor them into level-generic helpers
inside `chanlun.ts` (no contract change):

- `buildLegs(vertices)` → `Leg[]`
- `buildPivots(legs)` → `Pivot[]` (identical logic to today's inline scan)
- `markPoints(pivots, legs, legArea)` → `BuySellPoint[]` (identical logic;
  `legArea` stays a closure over the raw-bar MACD histogram — at segment
  level a leg spans from its start vertex's raw index to its end vertex's
  raw index, so the same Σ|hist| area proxy applies unchanged)

`computeChanlun`'s existing output (`vertices`, `zhongshus`, `points`) must
be **byte-identical** before/after the refactor (locked by the v1 test suite
+ a determinism assertion in the plan).

### 1.3 中枢升级 (pragmatic merge)

Post-pass over same-level zhongshus: while two **consecutive** zones overlap
in price (`max(zd1, zd2) < min(zg1, zg2)`), merge them into one level-2 zone:

- time span: `start = first.start`, `end = last.end`
- price span: **envelope** `[min(zd_i), max(zg_i)]` (display-pragmatic; the
  textbook recursion is explicitly not implemented — documented deviation)
- merged zones **replace** their constituents in the rendered set; a `level:
  1 | 2` field distinguishes them. Merging is transitive (3 consecutive
  overlapping zones → one level-2 zone).

### 1.4 区间套 (weekly×daily resonance)

- `resampleWeekly(bars)` in `chanlun.ts`: group daily bars by ISO week
  (`YYYY-Www` key derived from the date string), producing one
  `ChanlunBar` per week — `high = max`, `low = min`, `close = last`,
  `time = last session's date`. Run the unmodified `computeChanlun` on the
  weekly bars.
- **Resonance rule**: a **confirmed** daily 买卖点 `p` is resonant iff a
  same-side (B/S) **confirmed** weekly point `q` exists with
  `q.time ≤ p.time ≤ endOf(q's following weekly leg)` (the following leg's
  end-vertex time; if `q` is the last weekly vertex, the window extends to
  the last bar). Provisional points on either level never resonate.
- Output shape (pinned): `BuySellPoint` gains optional `resonant?: boolean`,
  set `true` only on resonant daily points; weekly-level results are not
  exposed outside the compute.

### 1.5 Public surface

`ChanlunResult` gains additive optional fields (non-breaking for v1
consumers/tests): `segVertices`, `segZhongshus`, `segPoints`, plus the
resonance marking per §1.4. Zhongshu gains `level` (defaults to 1). A single
entry point keeps the chart component simple:
`computeChanlunFull(bars)` → v1 result + segment-level structures + resonance
(internally calls `computeChanlun` once for daily, once for weekly).

## 2. Rendering (`TechnicalsPriceChart.tsx`; zero edits to the primitive)

- The existing single 缠论 toggle now draws both levels — no new controls.
- 笔: unchanged (thin `--text-secondary` polyline, solid + dashed tail).
- 线段: second solid/dashed `LineSeries` pair, `lineWidth: 2`, color
  `cssVar("--accent-warm")` (amber, distinct from the cool 中枢 tint).
- 段级中枢: a **second `ChanlunZhongshu` instance** attached to the price
  series with warm fill/border (`--accent-warm` at low alpha) — the
  primitive already takes per-instance options; it is not edited.
- 中枢升级: merged level-2 zones ride the 笔级 instance's data (they replace
  their constituent rects) and render with ordinary level-1 styling — their
  larger extent is the visual distinction; the `level` field is retained for
  future styling (per-rect colors would require editing the primitive).
- 段级买卖点: rendered on the shared marker plugin with a `段` text prefix
  (e.g. `段3B`) and marker size 2 (bi-level points stay size 1).
- 区间套: resonant markers get a `★` suffix (`3B★`); weekly structures are
  never drawn as chart layers (clutter). Legend gains the ★ explanation and
  a 线段 entry; the explainer prose extends by one sentence.
- All new series/primitives tear down with the existing toggle-off path.

## 3. Testing / verification (hardened — implementation by a non-Fable model)

- **Fixture**: extend to ~500 real apex daily bars (≈2 years) frozen with
  as-of comment, per the no-synthetic-data rule (real ticker, real prices,
  no network at test runtime). Ticker chosen at plan execution so the frozen
  data demonstrably exercises a case-2 缺口 (verified by running the built
  algorithm, not assumed); if AAPL's window lacks one, try NVDA/TSLA windows
  before considering a second fixture file.
- **Oracle tests**: hand-traced micro-sequences (from the chan.py source
  extraction embedded in the plan) with exact expected segment boundaries —
  at least one case-1 end, one case-2 confirmed, one case-2 failure where
  the segment continues.
- **Invariants** (vitest, on the frozen fixture):
  - v1 outputs byte-identical after the §1.2 refactor
  - segments alternate; each **confirmed** segment spans ≥3 strokes
    (provisional tail segments may be shorter, matching chan.py
    `is_sure=False` semantics); endpoints ⊂ stroke vertices
  - confirmed-prefix holds for `segVertices` (provisional only at the tail)
  - 段级中枢 `zg > zd`, time-ordered, within series range
  - merged zones arise only from consecutive price-overlapping zones;
    level-2 envelope contains its constituents; no surviving constituent
    rects alongside their merger
  - weekly resample conserves OHLC (`max/min/last` recomputable from the
    grouped daily bars; week keys strictly increasing)
  - resonant points ⊆ confirmed daily points, each with a matching
    confirmed weekly witness under the §1.4 window rule
  - determinism (`computeChanlunFull(bars)` deep-equals itself)
- **Suite gates** after every milestone: `cd web && npm run test`,
  `npx tsc --noEmit`, `npm run lint` — all green before proceeding.
- **Browser verification**: dev server smoke on AAPL (and one more ticker),
  screenshots to `output/playwright/chanlun-v2-*.png` showing 段 polyline,
  warm 段级中枢, a merged zone, and a ★ marker; toggle-off clears every layer.
- **Adversarial review**: a code-review pass over the diff before the PR is
  declared done (correctness of case-2 state machine and the refactor's
  output-identity are the two focus areas).

## 4. Delivery

- Merge PR #277 (v1) once CI is green; branch `feat/chanlun-v2` from `main`.
  Fallback if #277's CI drags: stack on `feat/chanlun-view`.
- One PR: code + tests + CHANGELOG `[Unreleased]` entry + v2 addendum section
  in the research doc + this spec (committed with the feature).
- No generated files touched (`web/lib/types.ts` untouched — no API change).
