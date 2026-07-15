# Chanlun (缠论) TypeScript → Python Port Contract

Source of truth: `web/lib/chanlun.ts` (574 lines) + `web/lib/chanlunSeg.ts` (429
lines), repo `/Users/chenxi/projects/argon`, commit range as of 2026-07-14
(`d57c85b` HEAD). Tests: `web/tests/lib/chanlun.test.ts`,
`web/tests/lib/chanlunFull.test.ts`, `web/tests/lib/chanlunSeg.test.ts`.
Renderer (data-shape reference only, NOT ported): `web/lib/lwc/chanlunZhongshu.ts`.

This document is the requirements source for the Python port. Every algorithm
claim below cites `file:line`. Where the TS source's own comments document a
deliberate deviation from textbook 缠论, that comment's substance is
transcribed, not paraphrased away.

**Scope note:** `computeChanlun` (笔/中枢/买卖点/背离, "v1") lives entirely in
`chanlun.ts`. `computeChanlunFull` ("v2") adds 线段 (segments, via
`chanlunSeg.ts::buildSegments`), 中枢升级 merging, 段级 pivots/points, and
weekly 区间套 resonance, all still inside `chanlun.ts`. The top-of-file
comment (`chanlun.ts:5-6`) says "线段 (segments) deliberately omitted" — this
is now **stale**: `chanlunSeg.ts` was added later and `computeChanlunFull`
does compute segments. Do not port that comment's claim as current behavior;
treat it as a historical note about v1's scope only.

---

## A. Type inventory

All from `web/lib/chanlun.ts` unless noted.

```ts
// chanlun.ts:15-20
type ChanlunBar = {
  time: string;   // 'yyyy-mm-dd'
  high: number;
  low: number;
  close: number;
};

// chanlun.ts:22-27  — one inclusion-merged candle
type MergedK = {
  high: number;
  low: number;
  hiIdx: number;   // raw-bar index (into the input ChanlunBar[]) carrying the merged high
  loIdx: number;   // raw-bar index carrying the merged low
};

// chanlun.ts:29-34  — a raw (pre-alternation) fractal candidate
type Fractal = {
  kind: "top" | "bottom";
  mIdx: number;    // index into the MergedK[] array
  rawIdx: number;  // raw-bar index of the extreme (= hiIdx or loIdx of the middle merged candle)
  price: number;   // high for top, low for bottom
};

// chanlun.ts:36-41  — a confirmed-alternating stroke endpoint (public/output shape)
type BiVertex = {
  time: string;
  price: number;
  kind: "top" | "bottom";
  confirmed: boolean;
};

// chanlun.ts:43-50
type Zhongshu = {
  start: string;    // time of the first leg's start vertex
  end: string;      // time of the last-inside-zone leg's end vertex
  zg: number;        // upper edge = min(high) of the defining strokes
  zd: number;        // lower edge = max(low)
  confirmed: boolean; // false while the trailing pivot is still extending
  level?: 1 | 2;      // present only on computeChanlunFull's post-merge output; absent on v1 output
};

// chanlun.ts:52  — six-way closed enum, no others
type BspKind = "1B" | "2B" | "3B" | "1S" | "2S" | "3S";

// chanlun.ts:54-60
type BuySellPoint = {
  time: string;
  price: number;
  kind: BspKind;
  confirmed: boolean;
  resonant?: boolean;  // set only by markResonance; absent (not false) otherwise
};

// chanlun.ts:64-69
type DivergenceMark = {
  time: string;
  price: number;
  kind: "top" | "bottom";
  confirmed: boolean;
};

// chanlun.ts:71-76  — computeChanlun's return type
type ChanlunResult = {
  vertices: BiVertex[];
  zhongshus: Zhongshu[];
  points: BuySellPoint[];
  divergences: DivergenceMark[];
};

// chanlun.ts:187-193  — internal working type threaded through legs/pivots/points
// (superset of BiVertex; carries rawIdx forward for MACD-area lookups)
type VertexPt = {
  time: string;
  price: number;
  kind: "top" | "bottom";
  rawIdx: number;
  confirmed: boolean;
};

// chanlun.ts:195-203  — one stroke (or one segment, when built over SegVertex-derived VertexPt)
type Leg = {
  hi: number;
  lo: number;
  up: boolean;   // true iff this leg's END vertex is a "top" (i.e. it rose)
  a: number;     // start vertex index (into the pts/VertexPt[] array the legs were built from)
  b: number;     // end vertex index
  rawA: number;  // raw-bar index of the start vertex (for MACD histogram lookups)
  rawB: number;  // raw-bar index of the end vertex
};

// chanlun.ts:205-212  — one pivot zone expressed over leg indices (pre-Zhongshu projection)
type Pivot = {
  firstLeg: number;      // index of the first of the 3 defining legs
  lastLeg: number;       // index of the last leg still touching [zd, zg]
  exitLeg: number | null; // index of the first leg fully outside; null while still extending
  exitUp: boolean;        // true iff the exit leg broke out above zg (exitLeg's lo > zg)
  zg: number;
  zd: number;
};

// chanlun.ts:528-532  — computeChanlunFull's return type
type ChanlunFullResult = ChanlunResult & {
  segVertices: SegVertex[];
  segZhongshus: Zhongshu[];
  segPoints: BuySellPoint[];
};
```

From `web/lib/chanlunSeg.ts`:

```ts
// chanlunSeg.ts:11-16  — public output of buildSegments; same shape/contract as BiVertex
type SegVertex = {
  time: string;
  price: number;
  kind: "top" | "bottom";
  confirmed: boolean;
};

// chanlunSeg.ts:18-22  — optional diagnostic counters, mutated in place if passed
type SegStats = {
  case1: number;            // segments that terminated via case-1 (no gap, immediate)
  case2Confirmed: number;   // case-2 (gap) terminations whose revert-fractal confirmed
  case2Provisional: number; // case-2 terminations still unconfirmed at series end
};

// chanlunSeg.ts:24-30  — internal: one stroke (笔) recast as a segment-building primitive
type Stroke = {
  idx: number;   // index into the strokes[] array = index into the (vertices.length-1) leg list
  up: boolean;
  hi: number;
  lo: number;
  sure: boolean; // both endpoint vertices confirmed
};

// chanlunSeg.ts:32  — internal
type CombineDir = "combine" | "included" | "up" | "down";

// chanlunSeg.ts:37-46  — internal: one feature-sequence element (chan.py CEigen)
type Elem = {
  hi: number;
  lo: number;
  up: boolean;      // MERGE direction, fixed once the element is created (not per-stroke)
  strokes: number[]; // stroke indices folded into this element, in feed order
  hiStroke: number;  // index of the stroke that currently carries the element's hi
  loStroke: number;  // index of the stroke that currently carries the element's lo
  lastHi: number;    // most-recently-folded stroke's own hi (chan.py actual_break state)
  lastLo: number;
};
```

Renderer-only shape (`web/lib/lwc/chanlunZhongshu.ts:19-25`, **not part of the
port** — included here only so the Python port's output can be reasoned about
independently of how it's consumed):

```ts
interface ZhongshuRect {
  start: Time; // lightweight-charts business-day string, same repr as Zhongshu.start
  end: Time;
  zg: number;
  zd: number;
  confirmed: boolean; // false → dashed border
}
```
The renderer consumes `Zhongshu.{start,end,zg,zd,confirmed}` directly (1:1
field names) — the Python port's `Zhongshu` output must keep these exact key
names if any downstream renders it. `level` is not consumed by the renderer.

---

## B. Constants

| Name | Value | File:line | Used in |
|---|---|---|---|
| `MIN_VERTEX_GAP` | `4` | `chanlun.ts:82` | `buildEndpoints` — opposite-kind fractal must be ≥4 merged-candle indices (`mIdx`) past the last accepted endpoint to be accepted (`chanlun.ts:168`) |
| `DIVERGENCE_RATE` | `0.9` | `chanlun.ts:84` | `markPoints` 1B/1S gate (`chanlun.ts:337`) and `markDivergences` gate (`chanlun.ts:374`) — both use strict `<` |
| min-bars threshold | `10` | `chanlun.ts:395` | `computeChanlun` returns `EMPTY_RESULT` if `bars.length < 10` |
| MACD fast/slow/signal | `12`, `26`, `9` | `chanlun.ts:180-183` | `macdHist` — hardcoded, not parameterized; ports must reproduce these exact periods |
| min confirmed-segment span | `3` (strokes) | `chanlunSeg.ts:352` | `buildSegments` — `sure = t===true && valueOk && fx.allBiSure() && endV-startV >= 3` |
| feature-sequence replay step | `2` | `chanlunSeg.ts:260` | `findRevertFx` steps `i += 2` — only same-parity (same-direction) strokes feed the reverse `EigenFX` |
| `MIN_VERTEX_GAP`/`DIVERGENCE_RATE` scope note | — | `chanlun.ts:78-84` | Comment: "ponytail: code constant, not a user setting — expose the old/new/4K variants only if chart parity with a reference product matters." Do not add a config surface for these in the port unless asked. |

No other named numeric constants exist in `chanlun.ts` or `chanlunSeg.ts`. `ema()`'s
smoothing factor `a = 2 / (period + 1)` (`web/lib/indicators.ts:21`) is derived,
not a separate constant, and is out of scope to re-litigate — just reproduce it
per-call with `period` bound to 12/26/9 as above.

---

## C. Pipeline, step by step

### C.1 `mergeInclusions` (包含处理) — `chanlun.ts:90-128`

Input: `ChanlunBar[]`. Output: `MergedK[]`.

Greedy, single left-to-right pass, one running "current merged candle" (`last`).
Direction state `dir: 1 | -1` seeded to `1` ("up") before the first bar
(`chanlun.ts:92`) — comment: *"first bars are warmup; the choice washes out"*
(`chanlun.ts:89`) because `dir` is only consulted once two bars have already
been found non-inclusive, at which point it's freshly reassigned anyway.

For each bar `b` at raw index `i`:
1. If there is no `last` (first bar), push a new `MergedK{high:b.high, low:b.low, hiIdx:i, loIdx:i}` and continue.
2. Test inclusion: `inc = (last.high >= b.high && last.low <= b.low) || (b.high >= last.high && b.low <= last.low)` — i.e. one candle's [low,high] range is a (non-strict) superset of the other's. **Strict `>=`/`<=`, no epsilon.**
3. If **not** inclusive: `dir = b.high > last.high ? 1 : -1` (strict `>`, tie → `-1`), then push a new standalone `MergedK` seeded from `b` (same as step 1). `last` is NOT mutated.
4. If inclusive, merge `b` into `last` **in place**, direction-dependent:
   - `dir === 1` ("up" merge): `if (b.high >= last.high) { last.high = b.high; last.hiIdx = i }` then `if (b.low > last.low) { last.low = b.low; last.loIdx = i }`. Note the asymmetry: high uses `>=` (ties move the index forward), low uses strict `>` (ties do NOT move the index).
   - `dir === -1` ("down" merge): mirror — `if (b.low <= last.low) { last.low = b.low; last.loIdx = i }` then `if (b.high < last.high) { last.high = b.high; last.hiIdx = i }`. Low uses `<=`, high uses strict `<`.

This tie-break asymmetry (`>=` on the "leading" edge of the current direction,
strict on the trailing edge) must be reproduced exactly — it affects which raw
bar `hiIdx`/`loIdx` point at when a merge doesn't move a given edge's extreme,
which in turn affects `rawIdx` on any fractal that lands on this candle.

Invariant asserted by `chanlun.test.ts:21-30`: no two consecutive output
candles are still mutually inclusive. Invariant asserted by
`chanlun.test.ts:32-37`: `bars[k.hiIdx].high === k.high` and
`bars[k.loIdx].low === k.low` for every merged candle.

### C.2 `findFractals` (分型) — `chanlun.ts:133-149`

Input: `MergedK[]`. Output: `Fractal[]` (raw, unfiltered, no alternation
enforced yet).

For `i` from `1` to `m.length-2` inclusive, look at the 3-window `[m[i-1], m[i], m[i+1]]`:
- **Top**: `b.high > a.high && b.high > c.high && b.low > a.low && b.low > c.low` (middle candle strictly dominates both neighbors on BOTH high and low). Emit `{kind:"top", mIdx:i, rawIdx:b.hiIdx, price:b.high}`.
- **Bottom**: `b.low < a.low && b.low < c.low && b.high < a.high && b.high < c.high`. Emit `{kind:"bottom", mIdx:i, rawIdx:b.loIdx, price:b.low}`.
- Otherwise: nothing emitted for this `i` (not mutually exclusive top/bottom by construction — a window failing both tests is simply skipped).

All four comparisons per branch are **strict** — a tie on either high or low at
either neighbor disqualifies the window as a fractal. This is the textbook
strict-fractal definition (not the "weak" 4-candle or same-high variants).

### C.3 `buildEndpoints` (笔 endpoint alternation, 新笔-style) — `chanlun.ts:154-175`

Input: `Fractal[]` (raw, chronological by construction since `findFractals`
walks `m` in order). Output: `Fractal[]` (alternating top/bottom, "同级别分型
覆盖" already resolved, gap rule already applied).

Single left-to-right pass over the raw fractal list, one running `eps` accumulator:
1. First fractal: pushed unconditionally.
2. Same kind as the last accepted endpoint (`f.kind === last.kind`, 中继分型 /
   同向分型 case): compare `better = f.kind==="top" ? f.price >= last.price : f.price <= last.price`
   (note: **non-strict** `>=`/`<=` — an exact tie on price REPLACES the
   existing endpoint with the later one). If better, **replace** `eps[eps.length-1]`
   in place (do not push). If not better, silently drop `f` (`continue`).
3. Opposite kind: **both** conditions must hold to accept:
   - `validGap = f.mIdx - last.mIdx >= MIN_VERTEX_GAP` (`>= 4`, on merged-candle
     index distance, not raw-bar distance).
   - `validPrice = f.kind==="top" ? f.price > last.price : f.price < last.price`
     (**strict** here — an opposite-kind fractal tying the previous endpoint's
     price is rejected).
   If both hold, push `f` as a new endpoint. If either fails, `f` is silently
   dropped — comment: *"too close / wrong side — ignored (a later, better
   fractal wins)"* (`chanlun.ts:172`). Critically: a rejected opposite-kind
   fractal does **not** become the new "last" for subsequent same-kind
   comparisons — the previous accepted endpoint remains `last` until a fractal
   actually satisfies both gap+price and gets pushed.

Net effect: the returned list strictly alternates top/bottom (enforced by
construction, not a post-hoc filter), and consecutive same-side pairs
monotonically move price in the trend direction (`chanlun.test.ts:72-78`
asserts every up-stroke's end price exceeds its start, every down-stroke's end
price is below its start — this follows directly from step 3's strict
price check plus step 2 always keeping the best same-kind candidate).

### C.4 MACD histogram (`macdHist`, private) — `chanlun.ts:179-185`

Input: `number[]` (closes, one per raw bar, same length/order as `bars`).
Output: `number[]`, same length, aligned 1:1 with the raw bar array.

```
e12 = ema(closes, 12)
e26 = ema(closes, 26)
dif[i] = e12[i] - e26[i]      // for all i
dea = ema(dif, 9)
hist[i] = dif[i] - dea[i]
```

`ema()` (`web/lib/indicators.ts:17-28`) is the *"pandas ewm(span=period,
adjust=False)"* formula per its own doc comment (`indicators.ts:15-16`):
`alpha = 2/(period+1)`; state `e` starts `null`; for each value `v`:
`if not finite(v): emit null` (state unchanged); else `e = e==null ? v : alpha*v + (1-alpha)*e`, emit `e`.
Because `computeChanlun` only ever calls this on `bars.map(b => b.close)` — and
`ChanlunBar.close` is always a real, finite float from market data — every
element of `e12`/`e26`/`dea` is non-null in practice, and the code's `as number`
casts (`chanlun.ts:182`) are safe *for real data*, but are NOT runtime-checked.
See §G.5 for the exact JS coercion behavior if a `null` ever did reach the
subtraction (relevant only for defensive test design, not normal operation).

**Do not use a library EMA (e.g. pandas `.ewm()`) without independently
verifying it reproduces this exact recursion bit-for-bit** — see §F for why
this specific function is the highest-risk spot for silent numeric divergence.

### C.5 Provisional-tail construction + `confirmedCount` semantics — `chanlun.ts:394-435`

This runs inside `computeChanlun`, after `buildEndpoints`. It is the most
stateful part of the pipeline and the one place "confirmed" is decided.

```
eps = buildEndpoints(findFractals(mergeInclusions(bars)))
if eps.length === 0: return EMPTY_RESULT
confirmedCount = eps.length - 1          // captured BEFORE any of the mutation below
tail = eps[eps.length - 1]               // the last endpoint buildEndpoints found
```

**Step (a) — extend the tail if the running same-direction extreme already beats it**
(`chanlun.ts:407-420`): scan merged candles `m[j]` for `j` from `tail.mIdx+1` to
the end. Track `extSame` = the most extreme same-kind candidate seen so far
(top: `m[j].high > (extSame ?? tail).price`; bottom: `m[j].low < (extSame ?? tail).price`;
both **strict**, and the comparison base is `extSame` once one has been found,
so it keeps sliding to the new max/min — this is NOT "beats the original tail
only", it's "beats whatever the running extreme is now"). If any `extSame` was
found, **replace** `eps[eps.length-1]` with it (same array slot, `confirmedCount`
unchanged since the array length didn't change).

**Step (b) — grow a forming counter-leg after the (possibly replaced) tail**
(`chanlun.ts:421-435`): let `anchor = eps[eps.length-1]` (post step-a). Scan
`m[j]` for `j` from `anchor.mIdx+1` to the end, looking for the OPPOSITE kind's
running extreme (top anchor → track lowest low; bottom anchor → track highest
high). `better = anchor.kind==="top" ? (!forming || m[j].low <= forming.price) : (!forming || m[j].high >= forming.price)`
— **non-strict** `<=`/`>=`, so a tie keeps sliding `forming` to the later
candle. If a `forming` fractal candidate was found, **push** it onto `eps`
(array length now `eps.length + 1`).

**Confirmed flag** (`chanlun.ts:437-450`, applied identically when building
both `vertices: BiVertex[]` and `pts: VertexPt[]`): `confirmed = i < confirmedCount`
where `i` is the FINAL index in `eps` after both (a) and (b). Since
`confirmedCount = (buildEndpoints output length) - 1`:
- Every endpoint from `buildEndpoints` **except the last** is `confirmed: true`.
- The last `buildEndpoints` endpoint (index `confirmedCount`) is **always
  provisional**, whether or not step (a) replaced it with an `extSame` value.
- Any appended `forming` vertex (index `confirmedCount+1`) is also provisional.
- **Edge case**: if `buildEndpoints` returned exactly 1 endpoint,
  `confirmedCount = 0`, so that single vertex is provisional (`0 < 0` is
  false) — i.e. it is possible for `vertices[0]` itself (the very first
  emitted vertex) to be unconfirmed. `chanlun.test.ts:80-86` only asserts the
  provisional flags form a *suffix* starting somewhere `> 0`, which holds on
  the real AAPL fixture but is not a universal guarantee from the algorithm —
  don't bake "index 0 is always confirmed" into the Python port as an
  invariant.

This is the mechanism behind the module doc-comment's warning
(`chanlun.ts:9-11`): *"The trailing structures are PROVISIONAL by
construction (the last stroke endpoint can still move, the forming
counter-leg tracks the running extreme) — consumers must render them
dashed/'?' and never alert off them."*

### C.6 `buildLegs` (笔/段 as legs) — `chanlun.ts:214-228`

Pure adjacent-pair transform, no filtering: for `i` from `0` to `pts.length-2`,
emit one `Leg` per consecutive vertex pair `(pts[i], pts[i+1])`:
`hi = max(price_i, price_i+1)`, `lo = min(...)`, `up = (pts[i+1].kind === "top")`,
`a=i, b=i+1`, `rawA = pts[i].rawIdx`, `rawB = pts[i+1].rawIdx`. Output length
= `pts.length - 1`. This function is level-agnostic — `computeChanlunFull`
reuses it verbatim over `segPts` (segment vertices) at `chanlun.ts:558`.

### C.7 `buildPivots` (中枢 on 笔/段) — `chanlun.ts:233-259`

Input: `Leg[]`. Output: `Pivot[]`. Sliding-window scan with a **non-uniform
advance** (this is not a fixed-stride window):

```
i = 0
while i <= legs.length - 3:
    trio = legs[i:i+3]
    zd = max(l.lo for l in trio)
    zg = min(l.hi for l in trio)
    if zg <= zd:                      # degenerate/non-overlapping trio — NOT a pivot
        i += 1
        continue
    lastLeg = i + 2
    exitLeg = None
    exitUp = False
    for j in range(i+3, len(legs)):
        if legs[j].lo > zg or legs[j].hi < zd:   # first leg fully outside [zd, zg]
            exitLeg = j
            exitUp = legs[j].lo > zg
            break
        lastLeg = j                    # still touching the zone — extend
    pivots.append({firstLeg:i, lastLeg, exitLeg, exitUp, zg, zd})
    i = exitLeg if exitLeg is not None else len(legs)   # <-- exit leg SEEDS the next window
```

Key details:
- `zg <= zd` uses `<=` — an exactly-touching trio (`zg == zd`, zero-width
  zone) is rejected, same as non-overlapping. Only `i += 1` (single-leg slide)
  on rejection, so the next trio starting one leg later is tried — this is how
  the window "hunts" for the first valid 3-leg overlap.
- Once a pivot is found, the loop does **not** resume at `i+1`; it jumps
  straight to `exitLeg` (or to the end of the array if `exitLeg` is still
  `None`, terminating the loop). Comment: *"the exit leg can seed the next
  structure"* (`chanlun.ts:256`) — i.e. leg `exitLeg` is simultaneously the
  pivot's exit AND a candidate `firstLeg` of the very next pivot's trio scan.
- `exitUp = legs[j].lo > zg` (the branch that fired `legs[j].lo > zg`) — note
  the `or` inside the exit test means EITHER `lo > zg` OR `hi < zd` triggers
  exit, but `exitUp` is computed by re-testing only `lo > zg` — if a leg
  somehow satisfies `hi < zd` without `lo > zg` (the expected/only realistic
  case for a break to the downside), `exitUp` correctly evaluates false. If a
  leg's `lo` and `hi` could both be inconsistent with a single direction this
  would be ambiguous, but a `Leg`'s `[lo,hi]` always brackets two real vertex
  prices so this can't happen in practice.
- A trailing pivot that never finds an exit leg (`exitLeg` stays `None`) is
  still emitted, with `lastLeg` = the last leg index that was ever inside the
  loop's scan (could be `legs.length-1` if the scan ran to the end without
  breaking).

`pivotsToZhongshus` (`chanlun.ts:261-273`) is a pure field projection, no
additional logic: `start = pts[legs[firstLeg].a].time`, `end =
pts[legs[lastLeg].b].time`, `zg`/`zd` passthrough, `confirmed = exitLeg != null`.

### C.8 `mergeOverlappingZhongshus` (中枢升级, pragmatic) — `chanlun.ts:279-294`

Single left-to-right pass with one running "current output zone" (`last =
out[out.length-1]`). For each input zone `z` in order:
- If `last` exists AND `max(last.zd, z.zd) < min(last.zg, z.zg)` (**strict**
  `<` — price ranges genuinely overlap, touching-but-equal does NOT count,
  verified by `chanlunFull.test.ts:119-125`), merge `z` into `last` **in
  place**: `last.zg = max(last.zg, z.zg)`, `last.zd = min(last.zd, z.zd)`,
  `last.end = z.end` (start is left untouched — the envelope's `start` is
  always the FIRST merged zone's original start), `last.confirmed = last.confirmed && z.confirmed`,
  `last.level = 2`.
- Else, push a copy of `z` with `level = z.level ?? 1` (i.e. defaults to 1 if
  not already set — relevant because this function can theoretically be
  chained, though in this codebase it's only ever called once, on raw v1
  `Zhongshu[]` which never carry a `level`).

This is applied only inside `computeChanlunFull` (`chanlun.ts:569`) to the
**stroke-level** (`daily.zhongshus`) zone list — the segment-level list
(`segZhongshus`) is NOT run through this merge (see `chanlun.ts:566-572`: the
returned `segZhongshus` comes straight from `pivotsToZhongshus(segPivots, ...)`,
never touching `mergeOverlappingZhongshus`).

Merging is **transitive by construction** because the pass is single-linear
and each merge widens `last` before the next comparison — three overlapping
zones in a row collapse into one level-2 zone (`chanlunFull.test.ts:109-117`).

### C.9 `markPoints` (三类买卖点) — `chanlun.ts:296-356`

Input: `pts: VertexPt[]`, `legs: Leg[]`, `pivots: Pivot[]`, `legArea: (Leg) => number`.
Output: `BuySellPoint[]`, time-sorted at the end.

For each pivot `p` at index `k` in `pivots` (iterate in order):

**3B/3S** (`chanlun.ts:308-320`) — only if `p.exitLeg != null`:
```
exitL = legs[p.exitLeg]
if p.exitUp and not exitL.up: mark("3B", exitL.b)
if (not p.exitUp) and exitL.up: mark("3S", exitL.b)
```
Transcribed reasoning from the inline comment (`chanlun.ts:308-315`), which is
a **deliberate, non-textbook-literal** derivation the port must preserve as
behavior, not just as commentary:
> "3B/3S: the exit leg IS the pullback. `buildPivots`' 'first leg fully
> outside [zd, zg]' is structurally always the counter-direction leg: a
> trend-direction leg fully above zg would need its start (a bottom vertex)
> above zg, which would make the PREVIOUS leg fully outside first. So the
> exit leg leaves the zone and fails to re-enter — its end vertex is the
> third-class point (its lo > zg / hi < zd already holds by the exit
> condition). The direction guard keeps a buy off a top vertex for degenerate
> inputs."

In other words: on real fractal-derived data, `exitL.up` is expected to always
be the OPPOSITE of `p.exitUp`'s implied breakout direction (the exit leg is
the pullback, not the breakout), so one of the two `if`s always fires and the
other never does — but both `if`s are coded (not `if/else`) specifically as a
"direction guard" defensive measure against inputs where that structural
invariant doesn't hold (e.g. the hand-built abstract test fixtures in
`chanlunFull.test.ts`). **The port must implement both independent `if`s, not
a single `if/else`.**

**1B/1S + 2B/2S** (`chanlun.ts:321-352`) — only evaluated once per pivot `p`
at index `k`, requires a valid *previous* pivot:
```
prev = pivots[k-1]
if prev is None or prev.exitLeg is None or p.exitLeg is None: return   # (this pivot's contribution ends here)
connect = legs[prev.exitLeg - 1]     # the BREAKOUT leg of the previous trend (just before its exit)
exit    = legs[p.exitLeg - 1]        # the BREAKOUT leg of the current trend
rising  = p.zd > prev.zg and connect.up and exit.up
falling = p.zg < prev.zd and (not connect.up) and (not exit.up)
newExtreme = pts[exit.b].price > pts[connect.b].price if rising else pts[exit.b].price < pts[connect.b].price
if (rising or falling) and newExtreme and legArea(exit) < DIVERGENCE_RATE * legArea(connect):
    first = "1S" if rising else "1B"
    mark(first, exit.b)
    retest = pts[exit.b + 2]          # may be undefined/out of range — guarded
    if retest is not None and retest.kind == pts[exit.b].kind:
        if first == "1B" and retest.price > pts[exit.b].price: mark("2B", exit.b + 2)
        if first == "1S" and retest.price < pts[exit.b].price: mark("2S", exit.b + 2)
```
Transcribed reasoning (`chanlun.ts:321-324`): *"1B/1S: trend (two
non-overlapping pivots) whose final BREAKOUT leg — the trend-direction leg
just before the counter-direction exit leg — makes a new extreme on weaker
MACD area than the previous pivot's breakout leg (趋势背驰)."* And for 2B/2S
(`chanlun.ts:341-342`): *"the first retest after the reversal leg holds the
1st-class extreme (no new low after 1B / no new high after 1S)."*

Notes on exact semantics, easy to get subtly wrong in a port:
- `connect`/`exit` are `legs[...exitLeg - 1]`, i.e. the leg **immediately
  before** each pivot's exit leg — NOT the exit leg itself, and not
  `lastLeg`. This is always well-defined because `exitLeg >= firstLeg+3 >= 3`
  when non-null.
- `rising`/`falling` require BOTH `connect.up` and `exit.up` to agree with the
  trend direction (a genuine "keeps rising/falling across two pivots"
  pattern) — a single mismatched leg direction disqualifies the whole 1B/1S
  check for this pivot pair. `p.zd > prev.zg` / `p.zg < prev.zd` requires the
  two pivots to be **non-overlapping** in price (a real "moved to a new
  range" condition, strict `<`/`>`).
  Note: unlike `mergeOverlappingZhongshus`' overlap test (§C.8) which is a raw
  `Math.max(zd)<Math.min(zg)` structural comparison, here it's the pivot
  RECORDS' own `zg`/`zd` fields being compared directly (`p.zd > prev.zg`),
  not a min/max recombination — same arithmetic result, just stated for
  clarity since the two functions look similar but aren't the same call.
- `legArea` is injected as a parameter, not baked into `markPoints` — see
  §C.11 for its two distinct call sites (stroke-level vs segment-level) and
  what raw-bar range it sums over.
- `retest = pts[exit.b + 2]` is a **fixed +2 offset** (the vertex two positions
  after the reversal vertex — i.e. the next same-kind vertex, since vertices
  strictly alternate kind by construction) — not a search for "the first
  retest meeting some condition" beyond that fixed offset. If `exit.b + 2` is
  out of bounds, `retest` is `undefined`/`None` and the whole 2B/2S branch is
  skipped for this pivot. **This is a "look exactly 2 vertices ahead" rule,
  not a scan.**
- `mark(kind, vIdx)` (`chanlun.ts:303-306`) pushes
  `{time: pts[vIdx].time, price: pts[vIdx].price, kind, confirmed: pts[vIdx].confirmed}`
  — the point directly inherits the underlying vertex's `confirmed` flag (no
  independent confirmation logic for points).

**Final sort** (`chanlun.ts:354`): `points.sort((a,b) => a.time.localeCompare(b.time))`
— string comparison, see §G.1 for the `localeCompare` vs ordinal-compare
caveat (verified safe for this exact string format, but flagged).

### C.10 `markDivergences` (顶/底背离, annotation-only) — `chanlun.ts:362-385`

Input: `pts`, `legs`, `legArea`. Output: `DivergenceMark[]`, in leg-scan order
(no explicit final sort — unlike `markPoints`, the natural iteration order
`i = 0, 1, 2, ...` over `legs` already yields chronological output since legs
are chronological and `i+2` only ever looks forward, so no sort step exists or
is needed).

```
for i in range(0, len(legs) - 2):
    a = legs[i]
    b = legs[i+2]     # always same direction as `a` (directions alternate every leg)
    extended = (pts[b.b].price > pts[a.b].price) if b.up else (pts[b.b].price < pts[a.b].price)
    if extended and legArea(b) < DIVERGENCE_RATE * legArea(a):
        v = pts[b.b]
        out.append({time: v.time, price: v.price, kind: v.kind, confirmed: v.confirmed})
```

Transcribed framing comment (`chanlun.ts:358-361`): *"顶背离/底背离 on 笔: legs
i and i+2 are always same-direction (directions alternate); flag the later
one when it pushes past the earlier one's extreme on weaker MACD area. Chart
annotation only — 买卖点 gating uses the pivot-anchored 趋势背驰 in
`markPoints`."* This is a **structurally simpler, textbook-adjacent** stroke
divergence check, deliberately distinct from and NOT reused by the
pivot-anchored 1B/1S check in `markPoints` (§C.9) — the two divergence checks
compare different leg pairs (`i`/`i+2` here vs `connect`/`exit` legs anchored
at pivot boundaries there) and are **not required to agree** on which pushes
get flagged. Do not try to unify them in the port.

### C.11 `legArea` — two call sites, both raw-bar MACD-histogram sums

Not a standalone exported function — defined inline as a closure at two call
sites, both with the identical body:
```
legArea(l) = sum(abs(hist[r]) for r in range(l.rawA + 1, l.rawB + 1))   # inclusive of rawB, EXCLUSIVE of rawA
```
- Stroke-level (`chanlun.ts:456-463`): `hist = macdHist(bars.map(b => b.close))`,
  closure captures this `hist`; passed into `markPoints`/`markDivergences` for
  the v1 (`computeChanlun`) result.
- Segment-level (`chanlun.ts:550-557`): **recomputed from scratch** — same
  `macdHist(bars.map(b => b.close))` call again (same raw bars, same result,
  just re-derived — not cached/shared with the stroke-level closure), then a
  structurally identical closure, passed into `markPoints` at `chanlun.ts:572`
  for `segPoints`. **Note:** `legArea` for segments still sums over
  **raw-bar** MACD histogram values (`hist[r]` indexed by raw bar, not by
  stroke or segment index) between the segment leg's `rawA+1` and `rawB`
  inclusive — i.e. segment-level 背驰 gating uses the same underlying
  per-day MACD histogram as stroke-level, just summed over a wider raw-bar
  span (a segment leg spans many strokes' worth of raw bars). Comment
  confirms this design choice (`chanlun.ts:535-536`): *"段级 legs reuse the
  level-generic pivot/BSP core; MACD-area 背驰 sums over the same raw-bar
  histogram, just across segment spans."*

### C.12 `resampleWeekly` — `chanlun.ts:472-494`

Input: `ChanlunBar[]` (daily). Output: `ChanlunBar[]` (one bar per ISO
calendar week, keyed by that week's Monday).

```
def monday(t: str) -> str:              # t is 'yyyy-mm-dd'
    d = parse_utc_midnight(t)           # chanlun.ts:474: new Date(`${t}T00:00:00Z`)
    offset = (d.getUTCDay() + 6) % 7    # Sun=0..Sat=6 -> Mon=0..Sun=6 "days since Monday"
    d = d - offset_days(offset)
    return d.isoformat_date()            # 'yyyy-mm-dd'
```
Grouping pass, single left-to-right scan, one running `key`:
- For each bar `b`: compute `k = monday(b.time)`.
- If this is the first bar output, OR `k != key`: start a **new** week bar —
  `key = k`; push a **shallow copy** of `b` unchanged (`{...b}` — so the first
  day's OHLC becomes the week's initial OHLC).
- Else (same week as the running bar): mutate the last pushed bar **in
  place**: `high = max(last.high, b.high)`, `low = min(last.low, b.low)`,
  `close = b.close` (overwritten every additional day — ends up being the
  LAST day's close), `time = b.time` (overwritten every additional day — ends
  up being the LAST day's date, NOT the Monday key `k`).

**Output `time` field is the last trading session's date within that calendar
week, not the Monday key** — this is asserted directly by the test
(`chanlun.test.ts` equivalent in `chanlunFull.test.ts:154-160`:
`expect(w.time).toBe(g[g.length-1].time)`). The Monday key is purely an
internal grouping key, never emitted.

See §G item 9 for the JS `Date.getUTCDay()` numbering vs Python `date.weekday()`
numbering — this is a load-bearing, easy-to-invert gotcha.

### C.13 `markResonance` (区间套) — `chanlun.ts:499-526`

Input: daily `points: BuySellPoint[]`, a full `weekly: ChanlunResult`
(computed by running `computeChanlun` on `resampleWeekly(bars)` — **not**
`computeChanlunFull**), `lastBarTime: string`. Output: a **new** array (never
mutates input points — verified by `chanlunFull.test.ts:383-390`), same
points, with `resonant: true` added to matching ones.

```
windows = []
for q in weekly.points where q.confirmed:
    vi = weekly.vertices.findIndex(v => v.time == q.time and v.price == q.price)   # first exact match
    to = weekly.vertices[vi+1].time if (vi >= 0 and vi+1 < len(weekly.vertices)) else lastBarTime
    windows.append({side: "B" if q.kind.endswith("B") else "S", from: q.time, to})
if not windows: return copy(points)
return [
    {**p, resonant: True} if (p.confirmed and any(w.side==side(p) and p.time>=w.from and p.time<=w.to for w in windows))
    else p
    for p in points
]
```
- `side(p) = "B" if p.kind.endswith("B") else "S"` (covers all 6 `BspKind`
  values unambiguously — `1B/2B/3B` end in "B", `1S/2S/3S` end in "S").
- The vertex lookup (`vi`) is a **linear scan for the first exact match** on
  BOTH `time` and `price` (not just time) — `Array.prototype.findIndex`
  returns `-1` if none found, in which case `vi >= 0` is false and `to`
  falls back to `lastBarTime` (the window extends to the end of the whole
  series).
- The window's `from` is the weekly point's own vertex time, `to` is the time
  of the vertex **immediately following** that weekly point's vertex in the
  weekly vertex list (i.e. the resonance window is "this weekly point's
  formation through the end of the leg it triggered"), per spec §1.4 cited in
  the doc comment (`chanlun.ts:496-498`).
- `p.time >= w.from && p.time <= w.time` is a **string comparison**
  (`yyyy-mm-dd` lexicographic == chronological for this format — see §G.1),
  inclusive both ends.
- Only `confirmed` daily points are eligible to become resonant
  (`p.confirmed &&` gate) — an unconfirmed point never gets the flag even if
  geometrically in-window (`chanlunFull.test.ts:358-364`, `p2`).
- A daily point failing the resonance test is returned **unchanged** (not
  `{...p, resonant: false}` — the field is simply absent, `undefined`, on
  non-resonant points). Ports using a language with mandatory struct fields
  (dataclasses, Pydantic) must model this as `Optional[bool] = None`
  (three-state: `None`=not evaluated/not resonant, not a `False` sentinel) or
  drop the field for non-resonant points if the target format allows optional
  keys — match whichever the golden-fixture JSON comparison (§F) expects.

### C.14 `computeChanlun` — top-level orchestration — `chanlun.ts:394-468`

```
if len(bars) < 10: return EMPTY_RESULT   # {vertices:[], zhongshus:[], points:[], divergences:[]}
m = mergeInclusions(bars)                 # §C.1
eps = buildEndpoints(findFractals(m))     # §C.2, §C.3
if len(eps) == 0: return EMPTY_RESULT
... provisional-tail construction ...     # §C.5 — mutates/extends `eps`
vertices = [BiVertex from each eps[i]]    # confirmed = i < confirmedCount
pts = [VertexPt from each eps[i]]         # same source, superset fields
legs = buildLegs(pts)                     # §C.6
pivots = buildPivots(legs)                # §C.7
zhongshus = pivotsToZhongshus(pivots, legs, pts)   # §C.7
hist = macdHist(bars.map(b => b.close))   # §C.4
legArea = <closure over hist>             # §C.11
points = markPoints(pts, legs, pivots, legArea)         # §C.9
divergences = markDivergences(pts, legs, legArea)       # §C.10
return {vertices, zhongshus, points, divergences}
```

### C.15 `computeChanlunFull` — top-level orchestration — `chanlun.ts:537-574`

```
daily = computeChanlun(bars)                                    # §C.14, full v1 result
segVertices = buildSegments(daily.vertices)                     # chanlunSeg.ts, §C.16
idxByTime = {b.time: i for i, b in enumerate(bars)}              # raw-bar time -> raw-bar index
segPts = [VertexPt from each segVertices[i], rawIdx = idxByTime.get(v.time, 0)]
hist = macdHist(bars.map(b => b.close))                          # recomputed, not shared with `daily`'s internal closure
segLegArea = <closure over this hist>                            # §C.11, segment call site
segLegs = buildLegs(segPts)                                      # §C.6, reused
segPivots = buildPivots(segLegs)                                 # §C.7, reused
weekly = computeChanlun(resampleWeekly(bars))                    # §C.12, §C.14 — full weekly v1 result
points = markResonance(daily.points, weekly, bars[bars.length-1]?.time ?? "")   # §C.13
return {
    ...daily,                                                    # vertices, zhongshus (v1, unmerged!), points (v1), divergences
    points,                                                       # OVERRIDES daily.points with the resonance-flagged version
    zhongshus: mergeOverlappingZhongshus(daily.zhongshus),        # OVERRIDES daily.zhongshus with §C.8's merged version
    segVertices,
    segZhongshus: pivotsToZhongshus(segPivots, segLegs, segPts),  # §C.7
    segPoints: markPoints(segPts, segLegs, segPivots, segLegArea),# §C.9, segment call site — NOT resonance-flagged
}
```
Key subtlety in the return-object construction: the spread `...daily` first
copies ALL of `daily`'s fields (`vertices`, `zhongshus`, `points`,
`divergences`), and then `points` and `zhongshus` are explicitly
**overwritten** by later keys in the same object literal (JS object literals:
later keys win). `divergences` is NOT overwritten — `computeChanlunFull`'s
`divergences` field is **exactly** `daily.divergences`, untouched by any v2
logic. `vertices` is likewise passed through from `daily` unchanged — asserted
by `chanlunFull.test.ts:42-47`: *"full.points may add resonant flags (Task 6)
and full.zhongshus may be merged (Task 5); vertices are the anchor that must
never move."* `segPoints` never goes through `markResonance` — only the daily
(stroke-level) `points` array gets resonance flags.

### C.16 `buildSegments` (线段) — `chanlunSeg.ts:279-428`

This is a batch, from-scratch port of chan.py's `seg_algo="chan"`
feature-sequence method (Vespa314/chan.py `Seg/SegListChan.py`,
`Seg/EigenFX.py`, `Seg/Eigen.py`, `Combiner/KLine_Combiner.py` — see
`chanlunSeg.ts:1-8`). It is meaningfully more intricate than the stroke
pipeline; treat this section as the highest-risk area for the port and budget
review time accordingly.

**Input transform** (`chanlunSeg.ts:284-293`): given `vertices: BiVertex[]`
(the fully-formed stroke vertex list, INCLUDING the provisional tail from
§C.5), build one `Stroke` per adjacent vertex pair:
```
strokes[i] = {
    idx: i,
    up: vertices[i+1].kind == "top",
    hi: max(vertices[i].price, vertices[i+1].price),
    lo: min(vertices[i].price, vertices[i+1].price),
    sure: vertices[i].confirmed and vertices[i+1].confirmed,   # BOTH endpoints confirmed
}
```
If `len(vertices) < 2`, return `[]` immediately.

**Outer loop** (`chanlunSeg.ts:296-356`) — repeatedly finds one segment
boundary at a time, advancing a `begin` cursor:
```
segs = []
begin = 0
loop:
    if begin >= len(strokes): break
    upE = EigenFX(up=True, strokes)     # fresh instance every outer-loop iteration
    downE = EigenFX(up=False, strokes)  # — resets EigenFX.actualBreakFlag "sticky" state each scan
    lastSegDir = segs[-1].up if segs else None
    fx = None
    for i in range(begin, len(strokes)):
        s = strokes[i]
        if (not s.up) and lastSegDir is not True:
            if upE.add(i): fx = upE
        elif s.up and lastSegDir is not False:
            if downE.add(i): fx = downE
        if len(segs) == 0:
            # --- first-segment bootstrap (see below) ---
            ...
        if fx: break
    if fx is None: break
    ...continues below (segment-record construction)...
```

Feed-direction gating: `upE` (looking for the END of an UP segment) is only
fed **down**-direction strokes (`not s.up`), and only while
`lastSegDir is not True` (i.e. not currently known to be inside an up
segment already — an up segment can't end again while still forming... more
precisely this is the standard "only feed the detector strokes that would
plausibly reverse the currently-assumed-or-unknown segment direction" gate).
Mirror for `downE`.

**First-segment bootstrap** (`chanlunSeg.ts:315-329`, only runs while
`segs.length === 0`, i.e. before any segment has been finalized):
```
if upE.ele[1] and not s.up:
    lastSegDir = False    # an imaginary predecessor segment is DOWN, so the real first segment is UP
    downE.clear()
elif downE.ele[1] and s.up:
    lastSegDir = True
    upE.clear()
if (not upE.ele[1]) and lastSegDir == False and not s.up:
    lastSegDir = None      # rollback: upE lost its 2nd element again
elif (not downE.ele[1]) and lastSegDir == True and s.up:
    lastSegDir = None
```
This lets the direction of the very first segment be provisionally inferred
as soon as EITHER detector accumulates a 2nd feature-sequence element
(`ele[1]` populated), and explicitly rolls that inference back
(`lastSegDir = None`) if the detector that triggered it subsequently loses
its 2nd element (via `EigenFX.reset()`, see below, dropping back to 0 or 1
elements). **Order matters**: the `if/elif` rollback checks run in the SAME
iteration as the `if/elif` inference above them, both gated on
`segs.length === 0`, both checked every stroke while no segment exists yet —
port this as two sequential (not merged) conditional blocks in the same loop
body, exactly as laid out.

**`EigenFX.add(si)`** (`chanlunSeg.ts:145-170`) — feed one stroke, return
`true` iff a fractal completed on this call:
```
s = strokes[si]; lst.append(si)
if ele[0] is None:
    ele[0] = newElem(s, this.up)     # merge dir = the detector's OWN segment-search direction
    return False
if ele[1] is None:
    if tryAdd(ele[0], s, excludeIncluded=True, allowTopEqual=0) == "combine":
        return False
    ele[1] = newElem(s, this.up)     # merge dir = segment-search direction AGAIN (not pairwise)
    impossible = (ele[1].hi < ele[0].hi) if this.up else (ele[1].lo > ele[0].lo)
    return self.reset() if impossible else False
# --- element 3 ---
lastEvidence = si
dir = tryAdd(ele[1], s, excludeIncluded=False, allowTopEqual=self.allowTopEqual)   # 1 if up else -1
if dir == "combine": return False
ele[2] = newElem(s, up=(dir == "up"))    # merge dir = LOCAL pairwise direction from tryAdd, NOT this.up
if not self.actualBreak(): return self.reset()
self.updateFx()
isFx = (self.fx == "top") if self.up else (self.fx == "bottom")
return isFx or self.reset()
```
Note the asymmetry already flagged by the source's own comment ordering:
element 1 and element 2 are always seeded with `newElem(s, this.up)` — the
detector's fixed search direction — while element 3 is seeded with
`newElem(s, dir === "up")` where `dir` came out of `tryAdd`'s **local**
pairwise combine test against element 2, which can differ from `this.up`.
This is the mechanism that lets element 3 represent a genuine direction
change relative to elements 1/2.

**`testCombine` / `tryAdd`** (`chanlunSeg.ts:62-116`) — chan.py's inclusion
test generalized to feature-sequence elements, with an `allowTopEqual` tri-state
(`0` neutral, `1` favors "down" on a tied high, `-1` favors "up" on a tied
low) and an `excludeIncluded` flag (when `true`, a stroke that would be fully
engulfed by the element, rather than extending it, is rejected as `"included"`
instead of silently folding in):
```
testCombine(el, s, excludeIncluded, allowTopEqual):
    if el.hi >= s.hi and el.lo <= s.lo: return "combine"        # el engulfs s
    if el.hi <= s.hi and el.lo >= s.lo:                          # s engulfs el
        if allowTopEqual==1 and el.hi==s.hi and el.lo>s.lo: return "down"
        if allowTopEqual==-1 and el.lo==s.lo and el.hi<s.hi: return "up"
        return "included" if excludeIncluded else "combine"
    if el.hi > s.hi and el.lo > s.lo: return "down"
    return "up"                                                  # el.hi < s.hi and el.lo < s.hi (only remaining case)
```
```
tryAdd(el, s, excludeIncluded, allowTopEqual):
    dir = testCombine(el, s, excludeIncluded, allowTopEqual)
    if dir != "combine": return dir
    flatNoExtend = (s.hi == s.lo) and (s.hi <= el.hi if el.up else s.lo >= el.lo)   # 一字 stroke that wouldn't move the envelope
    if not flatNoExtend:
        if el.up:
            if s.hi >= el.hi: el.hi = s.hi; el.hiStroke = s.idx
            if s.lo >= el.lo: el.lo = s.lo; el.loStroke = s.idx     # NOTE: >=, not >
        else:
            if s.lo <= el.lo: el.lo = s.lo; el.loStroke = s.idx
            if s.hi <= el.hi: el.hi = s.hi; el.hiStroke = s.idx     # NOTE: <=, not <
        el.lastHi = s.hi; el.lastLo = s.lo
    el.strokes.append(s.idx)
    return "combine"
```
`el.up`'s branch inside `tryAdd` uses **non-strict** `>=`/`<=` on BOTH edges
(unlike `mergeInclusions`'s asymmetric strict/non-strict split in §C.1) — a
tie on either edge still moves that edge's `*Stroke` index forward to the
newer stroke. `lastHi`/`lastLo` are unconditionally set to the incoming
stroke's own `hi`/`lo` whenever the "combine" branch actually folds it in
(i.e. whenever `not flatNoExtend`), which is the "actual_break" state chan.py
tracks per element.

**`actualBreak()`** (`chanlunSeg.ts:175-203`) — chan.py `EigenFX.actual_break`:
the counter-move must genuinely break past element 2's `lastLo`/`lastHi`; if
not, look ahead up to 2 more strokes for a delayed break, else — at the data
tail — accept anyway but flag it non-actual (`actualBreakFlag = False`, which
later maps to `canBeEnd()` returning `null`/provisional instead of `true`):
```
e1 = ele[1]; e2 = ele[2]
if (self.up and e2.lo < e1.lastLo) or ((not self.up) and e2.hi > e1.lastHi):
    return True
first = e2.strokes[0]; s0 = strokes[first]
n  = strokes[first+1]     # may not exist
nn = strokes[first+2]     # may not exist ("next same-direction stroke")
if nn is not None:
    breaks = (nn.lo < s0.lo) if self.up else (nn.hi > s0.hi)
    if breaks:
        self.lastEvidence = first + 2
        return True
    if (not nn.sure) or (first + 3 >= len(strokes)):
        self.actualBreakFlag = False
        return True
    return False
if n is not None:
    extending = (n.hi > e1.hi) if self.up else (n.lo < e1.lo)
    if extending: return False
    self.actualBreakFlag = False
    return True
self.actualBreakFlag = False
return True
```
Port this control flow exactly — the three `if nn / if n / else` branches are
NOT equivalent to a simpler "look 1 or 2 ahead" loop; each branch has its own
distinct fallback semantics (deferred `False` return to keep accumulating, vs
`True` return with the flag downgraded).

**`updateFx()`** (`chanlunSeg.ts:206-228`) — chan.py `Eigen.update_fx` fractal
test over the 3 elements, with the `allowTopEqual` tri-state baked in
(`ate = 1` if `this.up` else `-1`):
```
pre, mid, next = ele[0], ele[1], ele[2]
fx = None
if pre.hi < mid.hi and next.hi <= mid.hi and next.lo < mid.lo and (ate==1 or next.hi < mid.hi):
    fx = "top"
elif next.hi > mid.hi and pre.lo > mid.lo and next.lo >= mid.lo and (ate==-1 or next.lo > mid.lo):
    fx = "bottom"
gap = (fx=="top" and pre.hi < mid.lo) or (fx=="bottom" and pre.lo > mid.hi)
```

**`reset()`** (`chanlunSeg.ts:232-239`) — chan.py's `exclude_included`-branch
reset: drop the FIRST fed stroke index from `lst`, clear all element/gap/fx
state, and **replay** the remaining stroke indices through `add()` from
scratch, returning `true` as soon as any replay call returns `true` (early
exit), else `false` after exhausting the replay list. This is naturally
recursive (each replayed `add()` can itself call `reset()` again) — a
straightforward direct port (recursion or an explicit stack, either is fine
as long as the early-exit-on-first-`true` semantics match) is fine; do not
try to flatten it into an iterative fixed-point loop that changes when the
recursion actually terminates.

**`getPeakBiIdx()`** (`chanlunSeg.ts:243-246`): `(ele[1].hiStroke if self.up else ele[1].loStroke) - 1`
— the segment boundary is the STROKE **before** the one carrying element 2's
extreme (i.e. the segment's END vertex is that stroke's `b` = start of the
next stroke — see the `endV = endBi + 1` line in the outer loop below).

**`canBeEnd()`** (`chanlunSeg.ts:250-253`): `true` (confirmed) if `!this.gap`;
if `this.gap` is set, defers to `findRevertFx(getPeakBiIdx() + 2)`, which
returns `true`/`null` (never `false` — comment: *"chan.py removed the
threshold-break rejection (issue #272)"*, `chanlunSeg.ts:249`). If not `gap`,
result is `actualBreakFlag ? true : null` — **never explicitly `false`**
anywhere in this function; the type is `true | null` by design.

**`findRevertFx(beginIdx)`** (`chanlunSeg.ts:257-269`) — the case-2 (gap)
confirmation path: construct a **fresh** `EigenFX` with the **opposite**
direction (`!this.up`) over the SAME `strokes` array, then feed it strokes
starting at `beginIdx`, stepping by **2** (`i += 2`, same-parity strokes
only — i.e. only strokes matching the reverse detector's own required
direction, skipping every other stroke): the first call to `rev.add(i)` that
returns `true` yields a candidate; if `rev.actualBreakFlag` is false at that
point, downgrade the result to `null`; else return `true` (and record
`this.lastEvidence = rev.lst[-1]`). If the loop runs out of strokes without
`rev.add` ever returning `true`, or `beginIdx` is already out of `[0,
len(strokes))`, return `null`.

**`allBiSure()`** (`chanlunSeg.ts:271-276`): `false` if `lastEvidence` is set
and `strokes[lastEvidence].sure` is false; else `true` iff every stroke index
in `lst` has `sure === true`.

**Segment-record construction** (`chanlunSeg.ts:333-355`, continuing the
outer loop after `fx` is found):
```
endBi = fx.getPeakBiIdx()
t = fx.canBeEnd()                          # true | null
# (optional stats bookkeeping — see SegStats field mapping below)
startV = segs[-1].endV if segs else 0
endV = endBi + 1
valueOk = (vertices[endV].price > vertices[startV].price) if fx.up else (vertices[endV].price < vertices[startV].price)
if not valueOk and len(segs) == 0:
    begin = endBi + 1
    continue                                # skip-and-restart, FIRST SEGMENT ONLY (chan.py add_new_seg analog)
sure = (t is True) and valueOk and fx.allBiSure() and (endV - startV >= 3)
segs.append({endV, up: fx.up, sure})
begin = endBi + 1
if t is not True:
    break                                   # provisional tail segment found — stop the whole outer loop
```
`stats` bookkeeping (only if a `SegStats` accumulator was passed in,
`chanlunSeg.ts:335-340`):
```
if fx.gap:
    stats.case2Confirmed += 1 if t is True else 0
    stats.case2Provisional += 1 if t is not True else 0
elif t is True:
    stats.case1 += 1
```
Note: a non-gap, non-`True` result increments NEITHER counter (this can't
actually happen given `canBeEnd()`'s contract when `!gap` always returns
`true`-or-`null`, and `null` with `!gap` falls through incrementing nothing —
this is a real, if narrow, gap in the stats coverage; reproduce it exactly,
don't "fix" it to count that case).

**"Skip-and-restart" exception — first segment only** (`chanlunSeg.ts:348-351`):
if the candidate segment's value-direction check fails (`not valueOk`) AND no
segment has been recorded yet (`segs.length === 0`), the candidate is
discarded WITHOUT being pushed, `begin` is advanced to `endBi + 1` anyway, and
the outer loop `continue`s to search for the next boundary. **This
skip-and-restart path is only reachable while `segs.length === 0`** — for
every subsequent segment, a `valueOk` failure would still push a segment
record (with whatever `sure` value the `&&` chain computes — `valueOk` being
false makes `sure` false too, but the segment record is still appended, not
discarded). This is the "first-segment alternation exception" the task
description asks to be called out explicitly: **only the very first segment
boundary can be silently rejected and re-searched; every later boundary is
always recorded once found**, confirmed structurally, by `chanlunSeg.test.ts:88-96`'s
comment: *"chan.py CSeg.__init__ permits the FIRST segment to start on a
mismatched-kind vertex (start_bi.idx == 0 exception) — the series boundary
can cut mid-structure, so vertices[0]'s kind may equal the first segment
end's kind. Alternation binds from the second pair on."* (i.e. the alternation
invariant the test enforces is `if i >= 2: kind[i] != kind[i-1]` — the
FIRST segment, `i===1`, is explicitly exempted from the alternation check.)

**Outer loop termination**: the `for` loop over the outer `while(true)`
breaks when either (a) `begin >= strokes.length` at the top of an iteration,
or (b) an inner scan completes without any detector firing (`fx` stays
`null`), or (c) a segment was just recorded with `t !== true` (the "stop
scanning" `break` at `chanlunSeg.ts:355` — a provisional tail segment always
ends the whole segment-building pass, no further segments are searched past
it).

**`collect_left`** (`chanlunSeg.ts:358-407`) — after the main boundary-finding
loop exits, any remaining un-covered stroke range at the tail is converted
into alternating **provisional** (`sure: false`) segments tracking running
extremes, mirroring chan.py's "peak method" batch/display fallback:

*Sub-case: zero segments were ever found* (`chanlunSeg.ts:361-387`, only
runs if `segs.length === 0 and vertices.length > 1`): scan ALL vertices for
the single highest "top"-kind vertex (`hiIdx`, ties broken by taking the
LATER index — `v.price >= vertices[hiIdx].price`, non-strict) and the single
lowest "bottom"-kind vertex (`loIdx`, same tie rule, `v.price <= ...`,
non-strict). Compute the excursion from `vertices[0]` to each
(`upExc = vertices[hiIdx].price - vertices[0].price` or `-1` if no top vertex
exists at all; `dnExc` mirrored for bottoms). Pick whichever excursion is
larger (`upExc >= dnExc`, ties favor the UP excursion — non-strict `>=`); if
the picked index is `> 0`, push exactly one provisional segment
`{endV: pick, up: pick===hiIdx, sure:false}`.

*General extremes-walk* (`chanlunSeg.ts:388-407`, runs whenever `segs.length > 0`
after the step above, i.e. it always runs if there IS at least one segment,
whether from the main loop or from the zero-segments fallback just above):
```
while lastV < len(vertices)-1 and len(segs) > 0:
    wantTop = not segs[-1].up            # alternate direction from the last segment
    pick = -1
    for j in range(lastV+1, len(vertices)):
        v = vertices[j]
        match = (v.kind == "top") if wantTop else (v.kind == "bottom")
        if match and (pick==-1 or (v.price >= vertices[pick].price if wantTop else v.price <= vertices[pick].price)):
            pick = j                       # non-strict — ties take the LATER vertex
    if pick == -1: break                   # no matching vertex left at all — uncovered tail, leave it uncovered
    segs.append({endV: pick, up: wantTop, sure: False})
    lastV = pick
```
This walk can append MULTIPLE provisional segments per call (one per
alternating-direction extreme found), not just one — it keeps going until
either the vertex list is exhausted (`lastV == len(vertices)-1`) or no
matching-kind vertex remains ahead (`pick == -1`, which the comment says
"the 笔-level dashed tail shows it" — i.e. this is an accepted, intentional
gap in segment coverage when the stroke tail itself doesn't offer a
same-kind vertex to close the loop).

**Final output assembly** (`chanlunSeg.ts:409-428`):
```
if len(segs) == 0: return []
out = [SegVertex(vertices[0].time, vertices[0].price, vertices[0].kind, confirmed=segs[0].sure)]
for sg in segs:
    v = vertices[sg.endV]
    out.append(SegVertex(v.time, v.price, v.kind, confirmed=sg.sure))
return out
```
The FIRST output vertex is always `vertices[0]` verbatim, with `confirmed`
borrowed from the **first** segment's `sure` flag (not from `vertices[0].confirmed`
itself — i.e. a segment vertex's confirmed flag is entirely a segment-level
property, decoupled from the underlying stroke vertex's own confirmed state).
Every subsequent output vertex is `vertices[sg.endV]` with `confirmed =
sg.sure`.

---

## D. Known deliberate deviations from textbook 缠论

1. **中枢升级 is a flat, one-level overlap-merge, not textbook 九段升级
   recursion.** `chanlun.ts:275-278`: *"consecutive same-level zones whose
   [zd, zg] ranges overlap merge into one level-2 zone spanning both in
   time, with the price ENVELOPE [min(zd), max(zg)]. Documented deviation —
   textbook 九段升级 recursion is out of scope (spec §1.3). Transitive by
   construction."* Only two levels ever exist (`1` and `2`); there is no
   recursive re-merge of level-2 zones into level-3, even if three or more
   level-2 zones would themselves overlap after merging. Port this as a
   single non-recursive pass (§C.8), not a fixed-point loop.

2. **3B/3S derivation is a structural argument from `buildPivots`' exit
   condition, not the textbook "third-type point = pullback that holds
   outside the zone" tested independently.** The code relies on the claim
   that on real (fractal-derived) data, `buildPivots`' exit leg is always
   the counter-direction pullback (§C.9's transcribed comment,
   `chanlun.ts:308-315`) — this was a bug-fix discovery, not an original
   design choice: `chanlunFull.test.ts:206-214` records that an earlier
   version of the test oracles fed `buildPivots`/`markPoints` inputs
   violating this invariant (a "bottom" priced above a "top"), which "hid
   the fact that `buildPivots`' exit leg is ALWAYS the counter-direction
   pullback (zero BSPs on real data)" — i.e. a prior implementation
   silently produced zero 3B/3S points on all real data because it didn't
   rely on this invariant correctly. The current `markPoints` codes BOTH
   `if p.exitUp and not exitL.up` and `if not p.exitUp and exitL.up` as
   independent guards specifically so a future degenerate input can't
   silently mark the wrong side.

3. **1B/1S is pivot-anchored 趋势背驰 only — there is no leg-pairwise (笔背驰)
   first-class point check anywhere in `markPoints`.** The only "背驰"
   check contributing to `BuySellPoint`s compares the breakout leg of pivot
   `k` against the breakout leg of pivot `k-1` (§C.9); a single-leg or
   single-stroke-pair background divergence (as computed separately by
   `markDivergences`, §C.10, purely for the `divergences` annotation array)
   never produces a `BuySellPoint`.

4. **2B/2S is a fixed "next same-kind vertex two positions ahead" check,
   not a general retest search.** `chanlun.ts:341-342` transcribed above —
   the port must not "improve" this into a scan for the first retest
   satisfying the price condition; it is deliberately `pts[exit.b + 2]`
   and nothing else.

5. **顶背离/底背离 (`markDivergences`) is intentionally a separate, simpler
   same-direction-stroke-pair (`i`, `i+2`) check, decoupled from the
   pivot-anchored 1B/1S gate** — chart annotation only, explicitly not
   reused as the BSP gate (§C.10's transcribed comment). The two checks can
   and do disagree on which extremes get flagged; this is intentional, not
   a bug to reconcile in the port.

6. **`buildSegments`'s `canBeEnd()` never returns `false`, matching a
   specific upstream chan.py behavior change.** `chanlunSeg.ts:248-249`:
   *"true = confirmed end; null = provisional (tail). Never false — chan.py
   removed the threshold-break rejection (issue #272)."* If the Python port
   is cross-checked against an OLDER chan.py revision (pre-#272) that still
   has the threshold-break rejection, expect a discrepancy — this codebase
   intentionally tracks the post-#272 behavior.

7. **`computeChanlunFull` is a batch, from-scratch recompute of segments on
   every call — chan.py's incremental `do_init`/`used_to_be_sure` state
   machinery is deliberately not ported.** `chanlunSeg.ts:1-4`: *"chan.py
   seg_algo='chan' feature-sequence method, ported for BATCH recompute
   (chan.py is incremental; we rebuild from scratch each render, so
   do_init/used_to_be_sure machinery is unnecessary)."* The Python port
   should preserve this batch-recompute framing (recompute
   `computeChanlunFull`'s full segment structure from the full bar history
   every call) unless the target system has an explicit reason to add
   incremental state — that would be a scope expansion beyond this contract.

8. **Segment-level pivots/points reuse the exact same generic
   `buildLegs`/`buildPivots`/`markPoints` core as stroke-level, rather than
   a textbook-distinct 段级中枢/段级买卖点 derivation.** `chanlun.ts:534-536`:
   *"v1 result + segment-level structures. 段级 legs reuse the
   level-generic pivot/BSP core; MACD-area 背驰 sums over the same raw-bar
   histogram, just across segment spans."* This is a pragmatic code-reuse
   choice, not a textbook requirement — port it as literal reuse of the
   same functions (§C.6, §C.7, §C.9) over segment vertices, not a
   parallel reimplementation.

9. **`resampleWeekly` groups by plain ISO calendar week (Monday-keyed), not
   trading-week / exchange-calendar week.** Not flagged as a deviation in
   the source comments, but worth stating explicitly: holidays, partial
   weeks, and any non-Mon-Fri trading calendar are not specially handled —
   whatever daily bars exist for a given ISO week get grouped together,
   full stop.

---

## E. Numeric semantics

- **No epsilon/tolerance anywhere in `chanlun.ts` or `chanlunSeg.ts`.**
  Every comparison (`>`, `>=`, `<`, `<=`, `===`) operates on raw IEEE754
  doubles taken directly from bar `high`/`low`/`close` values, with no
  fuzzing. Confirmed by inspection of both files in full — no `1e-`,
  `epsilon`, `Number.EPSILON`, or `Math.abs(...) <` tolerance pattern
  appears anywhere in the compute pipeline (the renderer,
  `chanlunZhongshu.ts`, is out of scope and also has none). **The Python
  port must not add tolerance comparisons "for safety" — doing so changes
  behavior on ties and must be treated as a deviation requiring sign-off,
  not a hygiene improvement.**
- **No arithmetic ever reaches an output-visible numeric field except
  inside `macdHist`/`ema` (used only for internal gating comparisons, never
  emitted) and `legArea` (same, gating-only).** Every `price`/`zg`/`zd`
  value in every output type (`BiVertex`, `Zhongshu`, `BuySellPoint`,
  `DivergenceMark`, `SegVertex`) traces back to a `max`/`min`/direct-copy
  chain rooted in the original bar `high`/`low` values — never a `+`, `-`,
  `*`, or `/`. This is the load-bearing fact behind the parity-fixture
  recommendation in §F: these fields should be portable to **exact**
  equality, not tolerance-based equality.
- **Tie-break asymmetries are real and vary by function — do not assume a
  single global "ties favor X" rule.** Concretely, already itemized above
  but worth collecting here:
  - `mergeInclusions` up-merge: high uses `>=` (tie moves index), low uses
    `>` (tie does not move index); down-merge mirrors (`chanlun.ts:107-125`).
  - `findFractals`: all four comparisons per branch are strict — ties never
    qualify as a fractal (`chanlun.ts:137-146`).
  - `buildEndpoints`: same-kind replacement uses `>=`/`<=` (non-strict,
    ties replace); opposite-kind acceptance uses strict `>`/`<` on price
    (ties rejected) (`chanlun.ts:162-171`).
  - `buildPivots`: `zg <= zd` rejects zero-width zones (`<=`, non-strict)
    (`chanlun.ts:240`); exit test is `lo > zg || hi < zd` (strict on both)
    (`chanlun.ts:248`).
  - `mergeOverlappingZhongshus`: overlap test is strict `<`
    (`Math.max(...) < Math.min(...)`) — exact-touching zones do NOT merge
    (`chanlun.ts:283`).
  - `markPoints`/`markDivergences`: the `DIVERGENCE_RATE` gate is strict
    `<` — an exact 0.9 ratio does NOT count as divergence (verified by
    `chanlunFull.test.ts:309-310`: *"Equal leg areas -> ratio 1 >= 0.9 -> no
    divergence anywhere"*).
  - `chanlunSeg.ts::tryAdd`: envelope-edge updates use non-strict `>=`/`<=`
    on BOTH edges (unlike `mergeInclusions`'s split rule) — ties always
    move the stroke index forward (`chanlunSeg.ts:93-108`).
  - `chanlunSeg.ts::collect_left`: extreme-vertex tie-breaks are non-strict
    (`>=`/`<=`), always taking the LATER vertex on a tie
    (`chanlunSeg.ts:369-376`, `396-399`).
- **Index conventions — four distinct index spaces, never interchangeable:**
  1. **Raw-bar index** (`rawIdx`, `hiIdx`, `loIdx`, `rawA`, `rawB`) — 0-based
     position into the original input `ChanlunBar[]`/`bars` array. This is
     the ONLY index space `macdHist`'s output array and `legArea`'s
     summation range use.
  2. **Merged-candle index** (`mIdx`) — 0-based position into the
     `MergedK[]` array produced by `mergeInclusions`. Used only by
     `findFractals`'s window scan and `buildEndpoints`'s `MIN_VERTEX_GAP`
     check, and by the provisional-tail scan (§C.5) which walks `m[j]` by
     this index space.
  3. **Vertex/pts index** (`a`, `b`, `firstLeg`, `lastLeg`, `exitLeg`,
     `endV`, `startV`, and bare loop variables like `i`/`k`/`j` inside
     `buildLegs`/`buildPivots`/`markPoints`/`markDivergences`/`buildSegments`)
     — 0-based position into whichever `VertexPt[]`/`BiVertex[]`/`Stroke[]`
     array is currently in scope (stroke-level `pts`, or segment-level
     `segPts`, or `chanlunSeg.ts`'s `strokes[]` — these are three DIFFERENT
     arrays of DIFFERENT lengths that happen to share the same index
     conventions; do not conflate a stroke-level leg index with a
     segment-level leg index).
  4. **Pivot index** (`k` in `pivots.forEach((p,k) => ...)`, used only to
     look up `pivots[k-1]`) — 0-based position into the `Pivot[]` array.
  A Python port using plain lists/0-based indexing reproduces all four
  spaces identically — the risk is entirely in accidentally mixing spaces
  (e.g. using a merged-candle index to index into the raw-bar array), not
  in an off-by-one from language indexing conventions (both languages are
  0-based).
- **Time representation: plain `'yyyy-mm-dd'` strings throughout, zero
  `Date`/`datetime` objects in the compute pipeline itself.** All ordering
  and window comparisons (`markPoints`'s final sort via `.localeCompare()`,
  `markResonance`'s `>=`/`<=` window test, `chanlun.test.ts`'s
  `.localeCompare()` alternation checks) rely on lexicographic string
  ordering coinciding with chronological ordering for this fixed-width
  zero-padded ISO format. **The single exception** is `resampleWeekly`'s
  internal `monday()` helper (§C.12), which is the ONLY place actual date
  arithmetic occurs — parse to a UTC-midnight instant, extract day-of-week,
  subtract days, reformat to `'yyyy-mm-dd'`. Everywhere else, treat `time`
  as an opaque, lexicographically-sortable string; do not parse it to a
  `date` object "for convenience" since that risks introducing timezone or
  locale behavior the TS original never has.
- **`macdHist`/`ema` recursion order is exactly left-to-right, one state
  variable, no batching.** `e = e==null ? v : alpha*v + (1-alpha)*e`
  (`indicators.ts:25`) — a Python port must replicate this exact scalar
  recursion (a simple `for` loop with one running float) to have any hope
  of bit-identical output; a vectorized/library EMA (numpy cumulative
  filters, pandas `.ewm()`, scipy IIR filters) is **not guaranteed** to
  produce identical rounding even if "mathematically equivalent" — see §F
  for the concrete risk this poses to `legArea`-gated control flow (which
  points/divergences even appear, not just their values).

---

## F. Parity-fixture plan

### F.1 What must be verified, and why byte-for-byte JSON is the wrong target

Every numeric field actually emitted in every output type (`BiVertex.price`,
`Zhongshu.{zg,zd}`, `BuySellPoint.price`, `DivergenceMark.price`,
`SegVertex.price`) is provably a `max`/`min`/direct-copy of an input bar's
`high`/`low` (§E) — **no arithmetic**. Given identical input floats (the
frozen `AAPL_DAILY_2Y` fixture, reused verbatim — never re-fetch or
hand-edit it, per the repo's no-synthetic-data rule), a correct Python port
should reproduce every emitted numeric field **exactly** (`==`, not
`math.isclose`). The only computed (non-copy) floats in the whole pipeline
are `macdHist`'s EMA values and `legArea`'s sums, and NEITHER is emitted —
they only drive `<`/`>=`/`<=` gating decisions inside `markPoints` and
`markDivergences` (which points/divergences exist at all, and — via
`buildSegments`'s `sure` gate uses only booleans, not `legArea`, so segments
are unaffected by this risk entirely). This means:

- A **correct** port should pass an **exact-equality** check on every
  emitted field.
- The actual risk is not "off by a rounding error in the price" — it's "a
  near-tied `legArea` comparison flips because the Python EMA recursion
  rounds one ULP differently than the JS one, causing a DIFFERENT SET of
  points/divergences to appear" (an extra or missing array element, not a
  slightly-off value in an existing one).
- **Recommendation: exact field-by-field deep equality on every emitted
  output field (not string/byte JSON equality), PLUS a separate intermediate
  oracle on the raw `macdHist` array itself** (see F.3) to catch EMA
  divergence at its source, before it manifests as a confusing "wrong set of
  points" downstream failure.
- **Byte-for-byte raw JSON text equality is explicitly NOT recommended** as
  the acceptance gate, for a concrete, verified reason: Python's
  `json.dumps` always renders a `float` value that happens to be
  mathematically integral with a trailing decimal (`repr(196.0) ==
  "196.0"`), while JS's `JSON.stringify`/`Number.prototype.toString`
  renders the same value WITHOUT a decimal point (`String(196) === "196"`,
  and JS doesn't distinguish int/float at the type level at all — see the
  frozen snapshot `chanlunFull.test.ts.snap:73`: `"price": 196,` with no
  `.0`). A textually-correct Python port would therefore FAIL a naive
  byte-diff against a JS-produced golden file purely from this formatting
  divergence, producing a false negative on Day 1. Reaching true byte
  equality would require hand-rolling a custom Python JSON float encoder
  that mimics JS `Number`-to-string formatting (strip trailing `.0` when
  integral, else emit the shortest round-trip decimal) — extra engineering
  that buys nothing over exact structural equality, since structural
  equality already catches every case byte equality would (same double
  value ⟺ same shortest-round-trip string, for both V8 and CPython, which
  both implement a shortest-round-trip float-to-string algorithm — the ONLY
  divergence between them is exactly this int-vs-float rendering
  convention, not the underlying numeric algorithm).

### F.2 Concrete mechanism

1. **Do not invent a new fixture.** Reuse `AAPL_DAILY_2Y`
   (`web/tests/unit/fixtures/aaplDaily2y.ts`) exactly as-is — it is already
   a frozen, real-ticker, real-price, no-network fixture per this repo's
   standing rule, spanning 2024-07-12 → 2026-07-10 (505 lines,
   `high`/`low`/`close`/`as_of` per row, no `open`).
2. Add a small **golden-fixture generation script** on the TS side (does
   not exist yet — this is new, minimal code, not a behavior change to
   `chanlun.ts`/`chanlunSeg.ts`). Two viable placements, either is fine:
   - A new file, e.g. `web/scripts/chanlunGoldenFixture.ts`, runnable via
     `npx tsx` (or the project's existing TS-execution mechanism) — OR
   - A dedicated `it(...)` in a NEW test file (e.g.
     `web/tests/lib/chanlunGolden.test.ts`) that writes the golden JSON as
     a side effect the first time it's run, then asserts the checked-in
     file still matches on every subsequent run (mirrors the existing
     "byte-stable, never run `vitest -u`" discipline already established
     for `chanlunFull.test.ts:29-37`'s snapshot).
   Either way, the script must call:
   ```ts
   import { computeChanlunFull } from "@/lib/chanlun";
   import { AAPL_DAILY_2Y } from "../tests/unit/fixtures/aaplDaily2y";
   const bars = AAPL_DAILY_2Y.map(b => ({ time: b.as_of, high: b.high, low: b.low, close: b.close }));
   const full = computeChanlunFull(bars);
   ```
3. `macdHist` is currently a **private, unexported** function
   (`chanlun.ts:179`). To capture it as a separate oracle (F.3), either:
   (a) add `export` to its declaration — a zero-behavior-change,
   single-keyword diff, OR (b) reconstruct it inline in the golden script by
   calling the already-exported `ema` (`web/lib/indicators.ts`) with the
   exact same three calls chanlun.ts makes (`chanlun.ts:180-184`) — this
   requires zero changes to `chanlun.ts` but duplicates 4 lines of glue in
   the script. **Recommend (a)** — it's smaller, and keeps the oracle
   honest (calling the actual production function, not a hand-copied
   reimplementation of it that could silently drift).
4. Serialize the golden fixture as **one JSON file**, structured as:
   ```json
   {
     "vertices": [ {"confirmed": ..., "kind": ..., "price": ..., "time": ...}, ... ],
     "zhongshus": [ {"confirmed": ..., "end": ..., "level": ..., "start": ..., "zd": ..., "zg": ...}, ... ],
     "points": [ {"confirmed": ..., "kind": ..., "price": ..., "resonant": ..., "time": ...}, ... ],
     "divergences": [ {"confirmed": ..., "kind": ..., "price": ..., "time": ...}, ... ],
     "segVertices": [ {"confirmed": ..., "kind": ..., "price": ..., "time": ...}, ... ],
     "segZhongshus": [ {"confirmed": ..., "end": ..., "start": ..., "zd": ..., "zg": ...}, ... ],
     "segPoints": [ {"confirmed": ..., "kind": ..., "price": ..., "time": ...}, ... ],
     "macdHist": [ <one float per raw bar, in bar order> ]
   }
   ```
   Top-level and per-record key order should follow the same convention the
   codebase already uses for its frozen snapshot
   (`chanlunFull.test.ts.snap` — Vitest's `pretty-format` serializer sorts
   object keys alphabetically; e.g. `divergences`/`points`/`vertices` at
   top level, `confirmed`/`kind`/`price`/`time` per vertex record) — this
   is a convention, not a requirement, since the parity check (F.1) is
   structural, not textual, but keeping it consistent makes any manual
   diffing against the existing `.snap` file easier. `level` (on
   `Zhongshu`) and `resonant` (on `BuySellPoint`) are **optional** fields —
   when absent in the JS source (`undefined`), the JSON serialization must
   OMIT the key entirely (matching `JSON.stringify`'s own behavior of
   dropping `undefined`-valued object keys) rather than emitting `null` —
   the Python side's equality check must treat "key absent" and "key
   present with value `None`" as equivalent, or the golden writer must be
   equally careful to omit rather than null out.
5. Commit the resulting JSON as a **versioned fixture file** — e.g.
   `web/tests/lib/fixtures/chanlunGoldenAapl2y.json` on the TS side, copied
   verbatim (not regenerated independently) into the Python port repo's own
   test-fixtures directory. Treat regeneration with the same discipline as
   the existing snapshot: **never regenerate ad hoc**; any intentional
   change to `chanlun.ts`/`chanlunSeg.ts` that legitimately changes output
   must regenerate this file as an explicit, reviewed diff in the same PR
   (same "sanctioned re-baselines only" discipline as
   `chanlunFull.test.ts:29-33`).
6. **Python-side test**: load the committed JSON, run the Python port's
   `compute_chanlun_full` over the same `AAPL_DAILY_2Y` bars (the Python
   repo needs its own frozen copy of this exact fixture — same real
   ticker/prices/dates, transliterated, not re-fetched), and assert:
   - `vertices`, `zhongshus`, `points`, `divergences`, `segVertices`,
     `segZhongshus`, `segPoints`: each array has the same LENGTH, and each
     element matches the golden element on every field with **exact
     equality** (`==` on strings/bools, `==` on floats — not
     `math.isclose`), in the same order (all these arrays are
     chronologically/deterministically ordered by construction, never
     independently sorted in a way that could legitimately permute between
     implementations).
   - `macdHist`: same length, elementwise compared with a **tight but
     non-zero tolerance** (e.g. `abs(a - b) <= 1e-9`) — this is the one
     legitimate place to allow tolerance, specifically because it's an
     internal oracle used to LOCALIZE a divergence, not a public output
     field; if it fails, the port's EMA recursion (not just its output
     wiring) is the thing to fix, before even looking at points/divergences
     mismatches.
   - **Recommended test ordering**: check `macdHist` FIRST, then `vertices`
     (they never depend on `macdHist` at all — a `vertices` mismatch means
     the fractal/inclusion/endpoint pipeline is wrong, unrelated to MACD),
     then `zhongshus`/`segVertices`/`segZhongshus` (depend on `vertices`
     but not `macdHist`), then `points`/`segPoints`/`divergences` last
     (the only fields that depend on `macdHist` via `legArea`). This
     ordering turns "everything is wrong" into "here's the first stage
     that diverges," which is far more actionable than a flat diff of the
     whole structure.

### F.3 What this plan does NOT need

- No new market data, no synthetic fixtures — reuses the existing frozen
  `AAPL_DAILY_2Y` bars end to end (compute pipeline AND golden output).
- No dependency on the renderer (`chanlunZhongshu.ts`) — it's excluded from
  the port per the task scope, and the golden fixture never touches pixel
  coordinates.
- No `computeChanlun`-only (v1-only) golden file is strictly required in
  addition to the `computeChanlunFull` one, since `ChanlunFullResult`'s
  `vertices`/`divergences` are byte-identical to `computeChanlun`'s own
  output (§C.15) and `points`/`zhongshus` are supersets (resonance flags /
  merge) of the v1 fields — but if the Python port structures itself as two
  separate public functions (`compute_chanlun` and `compute_chanlun_full`),
  it's cheap and worthwhile to ALSO golden-check bare `compute_chanlun`
  output against the existing frozen Vitest snapshot's raw values (already
  visible in `chanlunFull.test.ts.snap`, computed over `AAPL_DAILY_2Y`) as
  a second, independent oracle — those values are already committed and
  don't require the new script at all for a first pass.

---

## G. Gotchas for a non-TS implementer

1. **`Array.prototype.sort` + `.localeCompare()` — safe here, but the
   safety is specific to this string format, not general.** `points.sort((a,b)
   => a.time.localeCompare(b.time))` (`chanlun.ts:354`) is a **stable**
   sort (JS `Array.sort` has been spec-guaranteed stable since ES2019 /
   V8's TimSort; Python's `list.sort()`/`sorted()` is also Timsort and also
   stable) — so stability itself isn't a divergence risk. The real trap is
   `localeCompare`: it's locale/ICU-aware collation, NOT raw
   code-point comparison, and its result can depend on the runtime's
   default locale. For the fixed-width, all-ASCII `'yyyy-mm-dd'` strings
   used throughout this codebase, locale-aware collation and plain ordinal
   comparison agree in every practical locale (digits and hyphens collate
   identically almost everywhere) — Python's plain `sorted(key=lambda p:
   p.time)` (ordinal string comparison) is a safe port. **Do not
   generalize this to "any string field can be ordinally compared"** if the
   port is ever extended to handle a differently-formatted time field.
2. **`arr[arr.length - 1]` is NOT the same idiom as Python's `arr[-1]`, and
   the difference bites specifically on empty arrays.** JS has no negative
   array indexing — `bars[-1]` in JS looks up the (nonexistent) property
   `"-1"` and evaluates to `undefined`, always, regardless of array length.
   `bars[bars.length - 1]` is the correct JS idiom for "last element," and
   when `bars` is empty, `bars.length - 1 === -1`, so `bars[-1]` (property
   lookup, not "wrap to last") again yields `undefined` — safely handled by
   the optional-chain fallback at the one call site that does this:
   `bars[bars.length - 1]?.time ?? ""` (`chanlun.ts:564`). **A naive
   "simplify to Python's negative indexing" port — `bars[-1].time if bars
   else ""` — happens to be correct here IF the empty-guard is kept, but
   `bars[-1]` WITHOUT the `if bars else` guard will raise `IndexError` in
   Python where the JS original silently produces `undefined`/`""`.**
   Always keep the explicit emptiness check when porting this specific call
   site; do not rely on Python's negative-indexing convenience without it.
3. **`??` (nullish coalescing) is NOT `or`.** JS `??` only falls back on
   `null`/`undefined`; Python's `or` falls back on ANY falsy value
   (`0`, `""`, `False`, `[]`, `{}`). Every `??` in this codebase
   (`p.exitLeg ?? legs.length` at `chanlun.ts:256`;
   `bars[bars.length-1]?.time ?? ""` at `chanlun.ts:564`;
   `z.level ?? 1` at `chanlun.ts:290`; `extSame ?? tail` at
   `chanlun.ts:411-412`, `chanlun.ts:415-417` — used as the comparison BASE
   inside a loop, not just a one-off default) must be ported as an explicit
   `x if x is not None else default` (or, in the loop-base cases, as an
   explicit `is None` check inside the loop body, not a Python `or`
   expression) — none of these fallback values happen to coincide with a
   legitimate "falsy but valid" case in THIS codebase (e.g. `exitLeg` is
   never legitimately `0`, since it's always `>= firstLeg+3 >= 3` when
   set), so a careless `or`-based port would likely pass on this specific
   fixture and silently be wrong in general — treat `??` → `is None`-guard
   as a hard rule, not something to verify case-by-case.
4. **`JSON.stringify`/JS `Number` formatting drops trailing `.0` on
   integral floats; Python's `json.dumps`/`repr(float)` does not.** Already
   covered in depth in §F.1 — restated here because it's the single most
   likely source of a false-negative "parity failure" if anyone DOES
   attempt raw-text JSON diffing despite §F's recommendation against it.
   `196` (JS) vs `196.0` (Python) for the exact same IEEE754 double value —
   this is a formatting-convention difference, not a computation
   difference, and must not be treated as a bug in the port.
5. **`null - null === 0` in JS numeric coercion — a latent, currently-inert
   trap in `macdHist`.** `dif[i] = (e12[i] as number) - (e26[i] as number)`
   (`chanlun.ts:182`) — the `as number` casts are compile-time-only
   assertions; if `ema()` ever actually returned `null` at some index (only
   possible if a `close` value were non-finite, which real market data
   never is, and which `computeChanlun` never guards against explicitly),
   JS's numeric coercion rules make `null - null` evaluate to `0` (both
   operands coerce to `0` via `ToNumber(null) === 0`), NOT `NaN` and NOT a
   thrown error. A literal Python port (`e12[i] - e26[i]` where both are
   `None`) would raise `TypeError: unsupported operand type(s)`, which is
   arguably better (fail loud) but is NOT what the JS reference does. Given
   this can't actually occur on real bar data, the recommended port
   behavior is to add an explicit input-validation guard (reject/assert
   finite closes at the `compute_chanlun` entry point) rather than trying
   to replicate `null - null == 0` coercion — but the implementer should
   know this is a deliberate policy choice (fail-fast on bad input) that
   diverges from "byte-identical to whatever the JS runtime happens to do,"
   in the one input class where the two can't agree without ugly coercion
   code.
6. **`Math.max(...arr)` / `Math.min(...arr)` on an empty array silently
   return `-Infinity`/`+Infinity`; Python's `max([])`/`min([])` raise
   `ValueError`.** Every use of this pattern in the codebase
   (`buildPivots`'s `Math.max(...trio.map(l => l.lo))` /
   `Math.min(...trio.map(l => l.hi))`, `chanlun.ts:238-239`) operates on a
   `trio` that is structurally guaranteed non-empty (always exactly 3
   elements, from `legs.slice(i, i+3)` inside a `while (i <= legs.length -
   3)` guard) — so this never actually triggers the empty-array case on
   real inputs. Still, a literal Python port using `max(l.lo for l in
   trio)` is safe as-is (never empty); do not add unnecessary
   `if not trio: ...` defensive handling that has no JS-side analog to stay
   parity-faithful, but also don't blindly copy the `Math.max(...arr)`
   spread pattern anywhere else in a way that could hit a genuinely empty
   array — audit every `max(...)`/`min(...)` call site during the port for
   whether emptiness is actually structurally excluded (it is, everywhere
   in this codebase, but this needs to be reverified per call site, not
   assumed).
7. **`Array.prototype.findIndex` returns `-1` on no match, not `None`/an
   exception.** Used at `chanlun.ts:507-509` (`markResonance`'s vertex
   lookup by exact `(time, price)` match) — the `vi >= 0` check right after
   it (`chanlun.ts:510-513`) is doing exactly the `-1`-sentinel check this
   requires. A Python port using `next((i for i, v in enumerate(...) if
   ...), -1)` reproduces the sentinel faithfully; using
   `list.index(...)` instead would raise `ValueError` on no match and
   requires an explicit `try/except` or membership pre-check — prefer the
   `next(..., -1)` idiom to keep the `>= 0` guard pattern intact and avoid
   introducing a new control-flow shape.
8. **JS `%` (remainder) vs Python `%` (modulo) sign convention — not
   actually triggered in this codebase, but worth flagging since date math
   is present.** JS's `%` returns a result with the sign of the DIVIDEND;
   Python's `%` returns a result with the sign of the DIVISOR. The only
   `%` in this codebase, `(d.getUTCDay() + 6) % 7` (`chanlun.ts:475`), only
   ever operates on non-negative operands (`getUTCDay()` returns `0..6`,
   `+6` keeps it non-negative, `%7` on a non-negative dividend agrees
   between JS and Python) — so this specific line ports safely with
   Python's plain `%`. Flagged only so the implementer doesn't assume this
   generalizes; if any FUTURE date/index arithmetic in a Python-side
   extension ever introduces a negative operand to `%`, the sign
   convention must be checked explicitly.
9. **JS `Date.prototype.getUTCDay()` numbering (`Sunday=0..Saturday=6`) is
   NOT the same numbering as Python `date.weekday()`
   (`Monday=0..Sunday=6`) — but they compose correctly if you know the
   mapping.** This is the single most load-bearing, easy-to-get-backwards
   gotcha in the whole file. Worked out explicitly:
   | Day | JS `getUTCDay()` | `(getUTCDay()+6)%7` (= chanlun.ts's "days since Monday") | Python `date.weekday()` |
   |---|---|---|---|
   | Monday | 1 | 0 | 0 |
   | Tuesday | 2 | 1 | 1 |
   | Wednesday | 3 | 2 | 2 |
   | Thursday | 4 | 3 | 3 |
   | Friday | 5 | 4 | 4 |
   | Saturday | 6 | 5 | 5 |
   | Sunday | 0 | 6 | 6 |
   The JS expression `(d.getUTCDay() + 6) % 7` (`chanlun.ts:475`) computes
   exactly the same integer, for every day, as Python's built-in
   `date.weekday()` — **directly**, with no further transform needed. The
   correct Python port of `monday(t)` is therefore:
   ```python
   from datetime import date, timedelta
   def monday(t: str) -> str:
       d = date.fromisoformat(t)          # 'yyyy-mm-dd', timezone-naive by construction — matches the JS 'T00:00:00Z' UTC-midnight framing
       offset = d.weekday()                # Monday=0..Sunday=6 — SAME integer as chanlun.ts's (getUTCDay()+6)%7, no further transform
       return (d - timedelta(days=offset)).isoformat()
   ```
   **The trap**: re-applying the `(x + 6) % 7` transform to Python's
   already-Monday-anchored `weekday()` (i.e. writing
   `(d.weekday() + 6) % 7` by pattern-matching the JS source too literally)
   silently computes the WRONG offset (it would compute "days since
   Tuesday" instead), shifting every week's grouping key by one day with no
   error or exception — this class of bug is exactly why the mapping table
   above is spelled out in full rather than asserted. Also use a
   timezone-naive `date` (not a timezone-aware `datetime`) throughout, to
   match the JS original's explicit `T00:00:00Z` UTC-midnight framing —
   there is no timezone-conversion behavior to replicate, only "parse the
   calendar date, do calendar-date arithmetic, format the calendar date
   back out."
10. **Optional/absent fields (`level?`, `resonant?`) are JS `undefined`,
    which `JSON.stringify` OMITS from the output entirely — not the same as
    an explicit `null`.** A Python `dataclass`/`TypedDict`/Pydantic model
    that always serializes every declared field (even as `null`) will NOT
    byte-match a JS-produced JSON blob for these two optional fields unless
    the Python serializer is configured to omit unset fields (e.g. Pydantic
    `model_dump(exclude_none=True)` or `exclude_unset=True`, chosen to match
    "was this field ever assigned" semantics, not "is this field currently
    falsy"). Since §F recommends structural (not textual) equality anyway,
    the practical rule is: the Python-side test comparator must treat "key
    absent" and "key present with value `None`" as equivalent for these two
    fields specifically, rather than requiring the golden JSON and the
    port's live output to agree on presence-vs-absence syntactically.
11. **`Array.prototype.slice(start, end)` is end-EXCLUSIVE, matching
    Python's `list[start:end]` exactly — no gotcha, confirmed for
    completeness.** Both `legs.slice(i, i+3)` (`chanlun.ts:237`) and
    `this.lst.slice(1)` (`chanlunSeg.ts:233`) port directly to `legs[i:i+3]`
    / `self.lst[1:]` with identical semantics (including Python's tolerance
    of `slice(1)`-style single-arg-to-end, `lst[1:]`, and both languages'
    tolerance of an end index past the array length).
12. **Division is plain float (`/`) throughout — never floor division —
    the only division in the whole pipeline is `ema`'s `alpha = 2 /
    (period + 1)` (`web/lib/indicators.ts:21`).** JS `/` is always
    floating-point division (no integer-division operator exists in JS at
    all). Python 3's `/` is likewise always true (float) division — a
    correct, unthinking transliteration (`2 / (period + 1)`) is already
    correct. The gotcha is purely a warning against instinctively reaching
    for Python's `//` out of habit from other languages where `/` on two
    integer literals means integer division — there is no such context
    here (`period` is always one of the `int` literals `12`/`26`/`9`, and
    `2 / 13` etc. must stay a float).
