# Chanlun Chart Trust-Styling Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restyle the existing Chanlun chart overlay so each mark's appearance reflects the trust-probe findings — trend-aligned 背离 bright, counter-trend/early faint, repaint-prone 1B/1S dimmed — client-side only.

**Architecture:** Two pure helpers (`sma`, `divergenceTrend`) added to `web/lib/chanlun.ts`, consumed by `TechnicalsPriceChart.tsx` where lightweight-charts markers are built. Trend flags come from a 200-SMA of the chart's own closes; marker `color` gets a per-tier rgba opacity (the codebase already appends 2-hex-digit alpha to `cssVar` values). No backend, no new chart primitive, no new toggle.

**Tech Stack:** Next.js 16 + React 19, TypeScript strict, lightweight-charts (price pane only), Vitest.

## Global Constraints

- **No new charting library** — lightweight-charts is the one documented exception, price pane only. No d3/recharts/visx.
- **Inline styles + CSS variables** (`var(--…)`); alpha via 2-hex-digit suffix on `cssVar` hex (established pattern: `${cssVar("--accent-cool")}80`).
- **`divergenceTrend` is a pure index-vs-SMA alignment fn → unit-tested with hand-built geometry** (a legitimate test double, not fabricated market data); `sma` on a plain numeric ramp. The real AAPL H1 fixture yields **0** divergences (verified), so it cannot drive the trend test.
- **No API/type change** → `npm run gen:types` NOT needed; `lib/types.ts` untouched.
- **Verification gates:** `cd web && npm run test`, `npm run typecheck`, `npm run build` — all must pass. Lint via `npm run lint`.
- **Never commit without an explicit user request** — commit steps below are drafted; wait for the operator's go.

**Reference — exact facts this plan relies on (verified in the repo 2026-07-18):**
- `web/lib/chanlun.ts`: `ChanlunBar = { time: string; high; low; close }`; `DivergenceMark = { time; price; kind: "top"|"bottom"; confirmed }`; `computeChanlun(bars) → { …, divergences }`.
- `TechnicalsPriceChart.tsx:80` `cssVar(name)` returns the CSS var value (hex). `:258-266` the `chanlunGeo` useMemo builds `bars: ChanlunBar[]` from `full` and returns `computeChanlunFull(bars)`. `:807-817` `marker()` helper builds point markers. `:818-841` divergence markers (`--accent-warm` circles). `:1064-1084` the Chanlun legend block (gated on `chanlunOn && candleMode`).
- Test approach: `divergenceTrend` is exercised with a hand-built `ChanlunBar[]` + `DivergenceMark[]` (closes `[10,20,5,20,5]`, `window=2`). The AAPL H1 fixture (`web/tests/unit/fixtures/aaplDaily2026H1.ts`, 130 bars) produces **0** divergences (verified by running `computeChanlun`), so it cannot exercise the branches — do not import it in this test.

---

### Task 1: Pure trust helpers in `chanlun.ts` (+ unit tests)

**Files:**
- Modify: `web/lib/chanlun.ts` (add two exported functions, e.g. after `markResonance`, before the `ChanlunFullResult` type at ~line 528)
- Create: `web/tests/lib/chanlunTrend.test.ts`

**Interfaces:**
- Produces:
  - `sma(closes: readonly number[], window: number): (number | null)[]` — rolling mean, `null` for the first `window-1` entries.
  - `divergenceTrend(bars: readonly ChanlunBar[], divergences: readonly DivergenceMark[], window?: number): (boolean | null)[]` — aligned to `divergences`; `true` = trend-aligned (底背离 close ≥ SMA / 顶背离 close < SMA), `false` = counter-trend, `null` = SMA undefined at that bar or time not found. Default `window = 200`.

- [ ] **Step 1: Write the failing test**

Create `web/tests/lib/chanlunTrend.test.ts`. Note: `divergenceTrend` is a **pure
index-vs-SMA alignment** function, so it is unit-tested with **hand-built geometry** —
a `ChanlunBar[]` + `DivergenceMark[]` whose close-vs-SMA relationships are known by
construction. This is a legitimate test double for a pure function, not market-data
fabrication. (The real AAPL H1 fixture is deliberately NOT used here: it contains 130
bars and produces **zero** divergences, so it cannot drive this test at any window.)
`sma` is tested on a plain numeric ramp.

```ts
import { describe, expect, it } from "vitest";

import {
  divergenceTrend,
  sma,
  type ChanlunBar,
  type DivergenceMark,
} from "@/lib/chanlun";

describe("sma", () => {
  it("nulls the warmup prefix and computes exact window means", () => {
    const s = sma([2, 4, 6, 8], 2);
    expect(s[0]).toBeNull();
    expect(s[1]).toBe(3); // (2+4)/2
    expect(s[2]).toBe(5); // (4+6)/2
    expect(s[3]).toBe(7); // (6+8)/2
  });
});

describe("divergenceTrend", () => {
  // closes = [10, 20, 5, 20, 5]; sma(closes, 2) = [null, 15, 12.5, 12.5, 12.5].
  const bars: ChanlunBar[] = [10, 20, 5, 20, 5].map((c, i) => ({
    time: `2024-01-0${i + 1}`,
    high: c + 1,
    low: c - 1,
    close: c,
  }));
  const divs: DivergenceMark[] = [
    { time: "2024-01-01", price: 10, kind: "bottom", confirmed: true }, // SMA null -> null
    { time: "2024-01-02", price: 20, kind: "bottom", confirmed: true }, // 20 >= 15    -> true
    { time: "2024-01-03", price: 5, kind: "bottom", confirmed: true }, //  5 >= 12.5   -> false
    { time: "2024-01-04", price: 20, kind: "top", confirmed: true }, //   20 <  12.5   -> false
    { time: "2024-01-05", price: 5, kind: "top", confirmed: true }, //     5 <  12.5   -> true
  ];

  it("flags each divergence by close-vs-SMA on its side; null in warmup", () => {
    expect(divergenceTrend(bars, divs, 2)).toEqual([
      null,
      true,
      false,
      false,
      true,
    ]);
  });

  it("returns null for a divergence whose time is not a bar", () => {
    expect(
      divergenceTrend(
        bars,
        [{ time: "1999-01-01", price: 0, kind: "bottom", confirmed: true }],
        2,
      ),
    ).toEqual([null]);
  });
});
```

- [ ] **Step 2: Run it to confirm it fails**

Run: `cd web && npm run test -- chanlunTrend`
Expected: FAIL — `sma`/`divergenceTrend` are not exported yet.

- [ ] **Step 3: Implement the helpers**

In `web/lib/chanlun.ts`, add (after `markResonance`, before `export type ChanlunFullResult`):

```ts
/** Simple moving average of `closes`; out[i] = mean of the trailing `window`
 * values, or null for the first window-1 entries. O(n) prefix-sum roll. */
export function sma(
  closes: readonly number[],
  window: number,
): (number | null)[] {
  const out: (number | null)[] = new Array(closes.length).fill(null);
  let run = 0;
  for (let i = 0; i < closes.length; i++) {
    run += closes[i];
    if (i >= window) run -= closes[i - window];
    if (i >= window - 1) out[i] = run / window;
  }
  return out;
}

/** Per divergence: is it trend-aligned? A 底背离 (bottom) is trend-aligned when
 * its bar closes ABOVE the `window`-SMA (dip inside an uptrend); a 顶背离 (top)
 * when it closes BELOW it. Returns true/false, or null when the SMA is not yet
 * defined at that bar (early history) or the time is not found. The trust probe
 * (docs/research/2026-07-18-chanlun-trust-silver) found the trend-aligned subset
 * carries the stronger honest edge. Aligned index-for-index to `divergences`. */
export function divergenceTrend(
  bars: readonly ChanlunBar[],
  divergences: readonly DivergenceMark[],
  window = 200,
): (boolean | null)[] {
  const idxByTime = new Map(bars.map((b, i) => [b.time, i]));
  const ma = sma(
    bars.map((b) => b.close),
    window,
  );
  return divergences.map((d) => {
    const i = idxByTime.get(d.time);
    if (i === undefined) return null;
    const m = ma[i];
    if (m === null) return null;
    return d.kind === "bottom" ? bars[i].close >= m : bars[i].close < m;
  });
}
```

- [ ] **Step 4: Run the test to confirm it passes**

Run: `cd web && npm run test -- chanlunTrend`
Expected: PASS (3 tests: 1 `sma`, 2 `divergenceTrend`).

- [ ] **Step 5: Typecheck**

Run: `cd web && npm run typecheck`
Expected: no errors.

- [ ] **Step 6: Commit** *(await explicit user go)*

```bash
git add web/lib/chanlun.ts web/tests/lib/chanlunTrend.test.ts
git commit -m "feat(web): sma + divergenceTrend trust helpers for chanlun overlay"
```

---

### Task 2: Wire trust-styling into the technicals chart overlay

**Files:**
- Modify: `web/components/stock/panels/TechnicalsPriceChart.tsx`

**Interfaces:**
- Consumes: `sma`/`divergenceTrend` (Task 1), existing `chanlunGeo`, `cssVar`, `positive`/`negative`, the marker builders.
- Produces: no new exports — internal rendering change only.

- [ ] **Step 1: Import `divergenceTrend`**

In the `@/lib/chanlun` import block (lines 44–49), add `divergenceTrend` after `computeChanlunFull` (value import before the `type` imports):

```ts
import {
  computeChanlunFull,
  divergenceTrend,
  type BuySellPoint,
  type ChanlunBar,
  type Zhongshu,
} from "@/lib/chanlun";
```

- [ ] **Step 2: Hoist bar construction so the effect can reach the bars**

Replace the `chanlunGeo` useMemo (currently ~lines 258–266) with a hoisted `clBars`
memo (so the marker effect can call `divergenceTrend(clBars, …)`) plus the unchanged
`chanlunGeo`:

```ts
  // Chanlun bars over FULL history (window-cut in the data pass), hoisted so the
  // marker effect can compute divergence trend without rebuilding them.
  const clBars = useMemo<ChanlunBar[] | null>(() => {
    if (!chanlunOn || !candleMode) return null;
    return full.flatMap((r) =>
      r.as_of != null && r.high != null && r.low != null && r.close != null
        ? [{ time: r.as_of, high: r.high, low: r.low, close: r.close }]
        : [],
    );
  }, [full, chanlunOn, candleMode]);
  const chanlunGeo = useMemo(
    () => (clBars ? computeChanlunFull(clBars) : null),
    [clBars],
  );
```

No separate trend memo / Map: `divergenceTrend` already returns an array index-aligned
to `chanlunGeo.divergences`, so the flags are zipped onto the marks *before* the
`firstAsOf` filter in Step 4 — strictly less machinery than a time-keyed Map.

- [ ] **Step 3: Dim repaint-prone base 1B/1S in the `marker()` helper**

In the marker effect (~line 807), give `marker()` a `dimFirst` flag and apply ~40% alpha to first-class points:

```ts
      const marker = (
        p: BuySellPoint,
        prefix: string,
        size: number,
        dimFirst: boolean,
      ) => {
        const buy = p.kind.endsWith("B");
        const base = buy ? positive : negative;
        const first = p.kind === "1B" || p.kind === "1S";
        return {
          time: p.time as Time,
          position: buy ? ("belowBar" as const) : ("aboveBar" as const),
          shape: buy ? ("arrowUp" as const) : ("arrowDown" as const),
          color: dimFirst && first ? `${base}66` : base, // ~40% for repaint-prone 1st points
          text: `${prefix}${p.kind}${p.confirmed ? "" : "?"}${p.resonant ? "★" : ""}`,
          size,
        };
      };
```

Update the two callers (base points dim; 段-level points unchanged):

```ts
          ...chanlunGeo.points
            .filter((p) => p.time >= firstAsOf)
            .map((p) => marker(p, "", 1, true)),
          ...chanlunGeo.segPoints
            .filter((p) => p.time >= firstAsOf)
            .map((p) => marker(p, "段", 2, false)),
```

- [ ] **Step 4: Tier the 背离 marker color by trend**

This edit is inside the `if (chanlunGeo) { … }` block (line 768), so `chanlunGeo` and
`clBars` are both non-null here. Replace `const divColor = cssVar("--accent-warm");`
(line 818) with the tier helper + the flags array:

```ts
      const divBase = cssVar("--accent-warm");
      const divColorFor = (t: boolean | null | undefined) =>
        t === true ? divBase : t === false ? `${divBase}59` : `${divBase}99`; // full / ~35% / ~60%
      // Index-aligned to chanlunGeo.divergences — zip before the firstAsOf filter.
      const divFlags = divergenceTrend(clBars!, chanlunGeo.divergences);
```

and replace the divergence `.map(...)` block (currently ~lines 827–839) with a
zip-then-filter that carries each mark's flag:

```ts
          ...chanlunGeo.divergences
            .map((mark, i) => ({ mark, trend: divFlags[i] }))
            .filter((x) => x.mark.time >= firstAsOf)
            .map((x) => ({
              time: x.mark.time as Time,
              position:
                x.mark.kind === "top"
                  ? ("aboveBar" as const)
                  : ("belowBar" as const),
              shape: "circle" as const,
              color: divColorFor(x.trend),
              text: `${x.mark.kind === "top" ? "顶背离" : "底背离"}${x.mark.confirmed ? "" : "?"}`,
              size: 1,
            })),
```

- [ ] **Step 5: Add `clBars` to the marker effect's dependency array**

The marker effect (`useEffect` at line 664) closes at line 874 with
`}, [rows, full, ticker, candleMode, anchor, mode, chanlunGeo]);`. Step 4 now reads
`clBars` inside it (`divergenceTrend(clBars!, …)`), so append `clBars`:

```ts
  }, [rows, full, ticker, candleMode, anchor, mode, chanlunGeo, clBars]);
```

(ESLint `react-hooks/exhaustive-deps` via `npm run lint` will flag it if missed.
`clBars` and `chanlunGeo` change together, so this adds no extra effect churn.)

- [ ] **Step 6: Append the trust sentence to the Chanlun legend**

In the legend block gated on `chanlunOn && candleMode` (~lines 1064–1084), append this
exact sentence as text children immediately before the block's closing `</div>` (line
1083). The leading `{" "}` forces a single separating space:

```tsx
{" "}Marker emphasis = reliability, not entry timing: bright 顶/底背离 = trend-aligned
(底 above / 顶 below the 200-DMA, the higher-conviction subset); faint 背离 =
counter-trend or early; faint 1B/1S = repaint-prone (24–34%). Not a trade signal.
```

- [ ] **Step 7: Typecheck + lint + build**

Run: `cd web && npm run typecheck && npm run lint && npm run build`
Expected: all clean (no unused `divColor`, no missing-dep warnings, build succeeds).

- [ ] **Step 8: Full test run**

Run: `cd web && npm run test`
Expected: green, including `chanlunTrend`.

- [ ] **Step 9: Browser verification**

Start the stack (`bash scripts/dev.sh` if not running), open a stock page with a
**long-history ticker (≥2y)**, Technicals tab, candle mode + Chanlun overlay ON. The
default `window=200` means the bright/faint split only appears where the 200-DMA is
defined; the chart feeds deep history (`full = fullRows ?? rows`, ~1650 daily bars), so
most divergences qualify — but a short-history name would render mostly faint, so pick a
long one. Confirm: some 底背离/顶背离 render bright and others faint; 1B/1S arrows are
visibly dimmer than 2B/3B/2S/3S; the legend sentence reads correctly. Save a screenshot
to `output/playwright/chanlun-trust-styling.png`.

- [ ] **Step 10: Commit** *(await explicit user go)*

```bash
git add web/components/stock/panels/TechnicalsPriceChart.tsx
git commit -m "feat(web): trust-styling on the chanlun overlay (trend-tiered 背离, dimmed 1B/1S)"
```

---

## Self-Review

**Spec coverage:**
- Trend-emphasis on 背离 (bright/faint/unknown tiers) → Task 1 `divergenceTrend` + Task 2 Step 4. ✓
- Dim repaint-prone 1B/1S, base points only (段 unchanged) → Task 2 Step 3. ✓
- One-line legend → Task 2 Step 6. ✓
- Client-side only, no backend/API/type-gen/toggle → no such files touched; `gen:types` explicitly not run. ✓
- Tests on hand-built geometry → Task 1 Step 1 (`divergenceTrend` is a pure alignment
  fn; the real AAPL H1 fixture has **0 divergences** — verified — so it can't drive it;
  `sma` on a ramp). ✓
- Honest caveat (reliability, not a trade signal) → legend sentence. ✓

**Placeholder scan:** none — every step carries runnable code or an exact command. Alpha constants (`66`/`59`/`99`) are concrete hex.

**Type consistency:** `divergenceTrend` signature identical across Task 1 (definition), Task 2 Step 4 (call), and the test; it returns `(boolean | null)[]` index-aligned to `chanlunGeo.divergences`, and `divColorFor` accepts `boolean | null | undefined` (array index access can be undefined) — consistent. `marker()` gains one `boolean` param, both callers updated.

**Simpler-approach check:** flags are zipped onto each divergence before the `firstAsOf` filter, so no time-keyed Map and no separate trend memo — the `clBars` hoist is the only added memo (and it removes a duplicated `flatMap`), keeping `chanlunGeo`'s shape unchanged so the ~8 downstream `chanlunGeo.*` reads and the `if (chanlunGeo)` guard are untouched. Marker opacity via alpha-suffixed `cssVar` reuses the codebase's existing idiom (verified: `TechnicalsPriceChart.tsx:444/466/467/499`).
