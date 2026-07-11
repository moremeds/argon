# Technicals Price Pane: MarketSmith Volume + SMA·σ ⇄ EMA·BB Toggle — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Port the MarketSmith volume treatment (prev-close coloring, MA50 line, low-vol graying/labels, HVE/HV1 labels, buzz readout) onto the Technicals price pane, and add a small header toggle switching the overlay between SMA20/50/200 + ±1.5σ band and EMA5/20/50 + Bollinger(20,2).

**Architecture:** Frontend-only. All new indicator math lives in a new pure module `web/lib/indicators.ts`, computed over the **full** (unwindowed) series then sliced to the visible window — EMA/BB/MA50/HV markers need pre-window history to be correct at the window's left edge. `TechnicalsTab` threads the full series to the chart via a new `fullRows` prop. The chart reuses its existing 3 LineSeries + BandsIndicator, refilled per mode. No backend change, no migration, no `gen:types`, no new dependency.

**Tech Stack:** Next.js 16 / React 19 / TypeScript strict, lightweight-charts ^5.2.0 (price pane only), Vitest.

**Spec:** `docs/superpowers/specs/2026-07-11-technicals-price-pane-volume-ma-toggle-design.md`

## Global Constraints

- **Styling is Argon, not Pine (user directive 2026-07-11):** no Pine RGB constants. Up volume `--positive`, down volume `--negative` (keep the existing `59` alpha suffix), low-rel-vol bars and low-vol labels `--text-muted`, volume-MA line `--warning`, marker/readout text follows the pane's existing 10px IBM Plex Mono style. Colors resolve via the pane's existing `cssVar()` helper.
- **No new npm dependencies.** lightweight-charts stays confined to the price pane (`TechnicalsPriceChart.tsx` + `lib/lwc/` + `lib/priceChartData.ts` + `lib/indicators.ts` type imports).
- **Tests use real frozen data** (project no-synthetic-data rule): the SPY fixture in Task 1 is real apex data frozen 2026-07-11; expected values below were computed independently with pandas at plan-authoring time. **Do not regenerate or "fix" fixture numbers or expected values** — if a test disagrees with an expected value, the implementation is wrong, not the constant.
- **Verification is mandatory per task** — this plan will be executed by a different model than the one that authored it. Every task ends with exact commands and expected output. Never mark a step done without running its command and seeing the expected result. If output differs, STOP and fix before proceeding; do not adjust expected constants to match your implementation.
- Working commands: `cd web && npm run test` (vitest), `npm run typecheck`, `npm run lint`. Run from `web/`.
- Branch: `feat/technicals-marketsmith-volume-overlay-toggle` in a worktree at `.worktrees/technicals-marketsmith/` (project rule: `.worktrees/<slug>/` is the only worktree location).
- Commit per task (user pre-authorized milestone commits for this plan). No `Co-Authored-By` trailers.
- CHANGELOG `[Unreleased]` entry rides this branch (Task 6), never a follow-up PR.

## Verified API facts (do not re-derive)

- lightweight-charts v5 markers: `import { createSeriesMarkers } from "lightweight-charts"` — `createSeriesMarkers(series, markers?)` returns `ISeriesMarkersPluginApi` with `.setMarkers(markers)` (pass `[]` to clear) and `.detach()`. Marker shape: `{ time, position: "aboveBar"|"belowBar"|"inBar", shape: "circle"|"square"|"arrowUp"|"arrowDown", color: string, id?, text?, size? }`. No third options argument.
- `TechnicalsResponse["series"][number]` (from `web/lib/types.ts` ~6618): `as_of: string` (required), `open/high/low/close/volume/sma20/sma50/sma200/z` all `?: number | null`.
- `sliceSeriesByTimeframe<T extends { as_of?: string | null }>(series, timeframe)` in `TechnicalsTab.tsx:47-77`; the tab renders `<TechnicalsPriceChart data={view} control={...} />` at `TechnicalsTab.tsx:456-459` where `view.series` is the windowed slice.
- `BandPoint` = `{ time: Time; upper: number; lower: number }` (`web/lib/lwc/bandsIndicator.ts:29-33`); `BandsIndicator.setBandData(bands: BandPoint[])`.
- localStorage precedent: `ReorderableList.tsx:17-26` — lazy `useState(() => load())`, `try/catch` around both get and set, safe because the component is client-only.

---

### Task 1: Frozen SPY fixture + core indicator math (`ema`, `sma`, `rollingStd`, `bollinger`)

**Files:**
- Create: `web/tests/unit/fixtures/spyBars.ts` (copy from scratchpad — see Step 1)
- Create: `web/lib/indicators.ts`
- Test: `web/tests/unit/indicators.test.ts`

**Interfaces (later tasks rely on these exact signatures):**
- Produces:
  - `type IndicatorBar = { as_of?: string | null; open?: number | null; close?: number | null; volume?: number | null }`
  - `ema(values: readonly (number | null | undefined)[], period: number): (number | null)[]`
  - `sma(values: readonly (number | null | undefined)[], period: number): (number | null)[]`
  - `rollingStd(values: readonly (number | null | undefined)[], period: number): (number | null)[]` — **population** std (ddof=0)
  - `bollinger(closes: readonly (number | null | undefined)[], period?: number, mult?: number): { upper: (number | null)[]; lower: (number | null)[] }`

- [ ] **Step 1: Install the frozen fixture**

The authoring session left the real fixture at `/private/tmp/claude-501/-Users-chenxi-projects-argon/9bdb69a2-cd9b-4980-b96c-6bec67cbc409/scratchpad/spyFixture.ts` (70 SPY daily bars, 2026-03-31 → 2026-07-10, from apex `http://100.66.147.98:8322/bars/SPY?timeframe=1d&limit=70`). Copy it verbatim:

```bash
mkdir -p web/tests/unit/fixtures
cp "/private/tmp/claude-501/-Users-chenxi-projects-argon/9bdb69a2-cd9b-4980-b96c-6bec67cbc409/scratchpad/spyFixture.ts" web/tests/unit/fixtures/spyBars.ts
```

If the scratchpad file is gone, re-fetch the SAME range from apex (`curl -s "http://100.66.147.98:8322/bars/SPY?timeframe=1d&limit=200"`) and keep exactly the bars 2026-03-31 through 2026-07-10; the expected values below are frozen to that range. Sanity anchors (must match exactly): first row `{ as_of: "2026-03-31", open: 638.94, high: 651.54, low: 637.98, close: 650.34, volume: 152534102 }`, last row `{ as_of: "2026-07-10", open: 752.05, high: 755.42, low: 748.1, close: 754.95, volume: 42431978 }`, `SPY_BARS.length === 70`.

- [ ] **Step 2: Write the failing tests**

`web/tests/unit/indicators.test.ts`:

```ts
import { describe, expect, it } from "vitest";
import { bollinger, ema, rollingStd, sma } from "@/lib/indicators";
import { SPY_BARS } from "./fixtures/spyBars";

// Expected values computed independently with pandas at plan-authoring time
// (2026-07-11) from this exact fixture:
//   ema  <-> close.ewm(span=N, adjust=False).mean()
//   sma  <-> close.rolling(N).mean()
//   std  <-> close.rolling(N).std(ddof=0)   (population — Bollinger convention)
// DO NOT edit these constants to make tests pass.
const closes = SPY_BARS.map((b) => b.close);

describe("ema", () => {
  it("matches pandas ewm(span, adjust=False) on real SPY closes", () => {
    const e5 = ema(closes, 5);
    const e20 = ema(closes, 20);
    const e50 = ema(closes, 50);
    expect(e5[0]).toBeCloseTo(650.34, 10); // seeded at first value
    expect(e5[4]).toBeCloseTo(656.5061728395062, 8);
    expect(e5[30]).toBeCloseTo(737.3643335649523, 8);
    expect(e5[69]).toBeCloseTo(750.2677023210776, 8);
    expect(e20[19]).toBeCloseTo(693.2104087055366, 8);
    expect(e20[69]).toBeCloseTo(744.9080264611164, 8);
    expect(e50[49]).toBeCloseTo(721.5231677698386, 8);
    expect(e50[69]).toBeCloseTo(734.1239811340163, 8);
  });

  it("emits null for null input and carries state across it", () => {
    const out = ema([10, null, 20], 5);
    expect(out[0]).toBeCloseTo(10, 10);
    expect(out[1]).toBeNull();
    // state carried: e = (2/6)*20 + (4/6)*10 = 13.333...
    expect(out[2]).toBeCloseTo(13.333333333333334, 10);
  });
});

describe("sma / rollingStd", () => {
  it("matches pandas rolling on real SPY closes", () => {
    const s20 = sma(closes, 20);
    const d20 = rollingStd(closes, 20);
    expect(s20[18]).toBeNull(); // warmup
    expect(s20[19]).toBeCloseTo(689.025, 8);
    expect(s20[69]).toBeCloseTo(743.8115, 8);
    expect(d20[19]).toBeCloseTo(22.296483018628784, 6);
    expect(d20[69]).toBeCloseTo(7.175446519207074, 6);
  });

  it("nulls any window containing a null", () => {
    const vals = [1, 2, null, 4, 5, 6];
    const out = sma(vals, 3);
    expect(out).toEqual([null, null, null, null, null, 5]);
  });
});

describe("bollinger", () => {
  it("mid ± 2·population-std on real SPY closes", () => {
    const bb = bollinger(closes, 20, 2);
    expect(bb.upper[18]).toBeNull();
    expect(bb.upper[69]).toBeCloseTo(758.1623930384142, 6);
    expect(bb.lower[69]).toBeCloseTo(729.4606069615859, 6);
  });
});
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `cd web && npx vitest run tests/unit/indicators.test.ts`
Expected: FAIL — `Cannot find module '@/lib/indicators'` (or equivalent resolve error).

- [ ] **Step 4: Implement `web/lib/indicators.ts` (math section)**

```ts
// Pure indicator math for the Technicals price pane. Client-side mirror
// precedent: lib/vwap.ts (anchoredVwap). Computed over the FULL series and
// windowed by the caller — EMA/rolling windows need pre-window history.

export type IndicatorBar = {
  as_of?: string | null;
  open?: number | null;
  close?: number | null;
  volume?: number | null;
};

const fin = (v: number | null | undefined): v is number =>
  v != null && Number.isFinite(v);

/** pandas ewm(span=period, adjust=False): alpha = 2/(period+1), seeded at the
 * first finite value. Null input emits null; state carries across it. */
export function ema(
  values: readonly (number | null | undefined)[],
  period: number,
): (number | null)[] {
  const a = 2 / (period + 1);
  let e: number | null = null;
  return values.map((v) => {
    if (!fin(v)) return null;
    e = e == null ? v : a * v + (1 - a) * e;
    return e;
  });
}

/** pandas rolling(period).mean() with min_periods=period: null until the
 * window is full, and null for any window containing a non-finite value. */
export function sma(
  values: readonly (number | null | undefined)[],
  period: number,
): (number | null)[] {
  const out: (number | null)[] = new Array(values.length).fill(null);
  let sum = 0;
  let bad = 0;
  for (let i = 0; i < values.length; i++) {
    const v = values[i];
    if (fin(v)) sum += v;
    else bad++;
    if (i >= period) {
      const o = values[i - period];
      if (fin(o)) sum -= o;
      else bad--;
    }
    if (i >= period - 1 && bad === 0) out[i] = sum / period;
  }
  return out;
}

/** Rolling POPULATION std (ddof=0) — Bollinger/Pine ta.stdev convention. */
export function rollingStd(
  values: readonly (number | null | undefined)[],
  period: number,
): (number | null)[] {
  const out: (number | null)[] = new Array(values.length).fill(null);
  let sum = 0;
  let sumsq = 0;
  let bad = 0;
  for (let i = 0; i < values.length; i++) {
    const v = values[i];
    if (fin(v)) {
      sum += v;
      sumsq += v * v;
    } else bad++;
    if (i >= period) {
      const o = values[i - period];
      if (fin(o)) {
        sum -= o;
        sumsq -= o * o;
      } else bad--;
    }
    if (i >= period - 1 && bad === 0) {
      const mean = sum / period;
      // clamp tiny negative from float error
      out[i] = Math.sqrt(Math.max(0, sumsq / period - mean * mean));
    }
  }
  return out;
}

/** Bollinger envelope: sma(period) ± mult · rollingStd(period). */
export function bollinger(
  closes: readonly (number | null | undefined)[],
  period = 20,
  mult = 2,
): { upper: (number | null)[]; lower: (number | null)[] } {
  const mid = sma(closes, period);
  const sd = rollingStd(closes, period);
  const upper = mid.map((m, i) => {
    const d = sd[i];
    return m != null && d != null ? m + mult * d : null;
  });
  const lower = mid.map((m, i) => {
    const d = sd[i];
    return m != null && d != null ? m - mult * d : null;
  });
  return { upper, lower };
}
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd web && npx vitest run tests/unit/indicators.test.ts`
Expected: PASS — every expected constant above must pass WITHOUT modification. If `rollingStd` misses by a small margin, you used sample std (ddof=1) — the convention here is population (ddof=0). If `ema[19]` is off, you seeded with an SMA (TA-Lib convention) — the convention here is seed-at-first-value (pandas `adjust=False`).

- [ ] **Step 6: Typecheck and commit**

```bash
cd web && npm run typecheck
git add web/lib/indicators.ts web/tests/unit/indicators.test.ts web/tests/unit/fixtures/spyBars.ts
git commit -m "feat(web): indicator math lib (ema/sma/std/bollinger) + frozen SPY fixture"
```

---

### Task 2: Volume analytics (prev-close direction, lowest-in-window, MA, markers, compact format)

**Files:**
- Modify: `web/lib/indicators.ts` (append)
- Test: `web/tests/unit/indicators.test.ts` (append)

**Interfaces:**
- Consumes: `sma`, `IndicatorBar`, `fin` from Task 1.
- Produces (exact — Task 3/5 import these):
  - `prevCloseUp(rows: readonly IndicatorBar[]): (boolean | null)[]`
  - `lowestInWindow(volumes: readonly (number | null | undefined)[], window?: number): boolean[]` (default 10)
  - `volumeMa(volumes: readonly (number | null | undefined)[], period?: number): (number | null)[]` (default 50)
  - `fmtVolCompact(v: number): string` — `42431978 → "42.43M"`, `152534102 → "152.53M"`, `1234 → "1.23K"`, `999 → "999"`
  - `type VolMarker = { time: string; position: "aboveBar" | "belowBar"; shape: "circle"; color: string; text: string; size: number }`
  - `lowVolMarkers(rows: readonly IndicatorBar[], ma: readonly (number | null)[], opts: { thresholdPct?: number; color: string }): VolMarker[]` (default thresholdPct −25)
  - `highVolMarkers(rows: readonly IndicatorBar[], opts: { oneYear?: number; peakLen?: number; color: string }): VolMarker[]` (defaults 252 / 9)

- [ ] **Step 1: Write the failing tests (append to `indicators.test.ts`)**

```ts
import {
  fmtVolCompact,
  highVolMarkers,
  lowVolMarkers,
  lowestInWindow,
  prevCloseUp,
  volumeMa,
} from "@/lib/indicators";

describe("prevCloseUp", () => {
  it("colors by previous close, falling back to open on the first bar", () => {
    const up = prevCloseUp(SPY_BARS);
    expect(up[0]).toBe(true); // 650.34 >= open 638.94 (no prev close)
    expect(up[1]).toBe(true); // 655.24 >= 650.34
    // 2026-07-08: close 745.40 > open 743.16 (green candle) but < prev close
    // 747.71 — the case where prev-close coloring DIFFERS from bar direction.
    expect(SPY_BARS[67].as_of).toBe("2026-07-08");
    expect(up[67]).toBe(false);
  });

  it("emits null when close is null", () => {
    expect(prevCloseUp([{ close: null, open: 1 }])).toEqual([null]);
  });
});

describe("lowestInWindow", () => {
  it("flags trailing-10 minima on real SPY volume (pandas rolling(10).min parity)", () => {
    const flags = lowestInWindow(
      SPY_BARS.map((b) => b.volume),
      10,
    );
    const dates = SPY_BARS.filter((_, i) => flags[i]).map((b) => b.as_of);
    expect(dates).toEqual([
      "2026-04-27",
      "2026-05-21",
      "2026-05-22",
      "2026-05-26",
      "2026-06-02",
      "2026-06-22",
      "2026-07-07",
      "2026-07-09",
    ]);
  });
});

describe("volumeMa / fmtVolCompact", () => {
  it("MA50 matches pandas on real SPY volume", () => {
    const ma = volumeMa(
      SPY_BARS.map((b) => b.volume),
      50,
    );
    expect(ma[48]).toBeNull();
    expect(ma[49]).toBeCloseTo(55241595.14, 2);
    expect(ma[69]).toBeCloseTo(53919783.64, 2);
  });

  it("formats K/M/B", () => {
    expect(fmtVolCompact(42431978)).toBe("42.43M");
    expect(fmtVolCompact(152534102)).toBe("152.53M");
    expect(fmtVolCompact(1234)).toBe("1.23K");
    expect(fmtVolCompact(999)).toBe("999");
    expect(fmtVolCompact(2500000000)).toBe("2.5B");
  });
});

describe("lowVolMarkers", () => {
  const ma = volumeMa(
    SPY_BARS.map((b) => b.volume),
    50,
  );
  it("no bar is 25% below MA50 on this fixture", () => {
    expect(lowVolMarkers(SPY_BARS, ma, { thresholdPct: -25, color: "#888" })).toEqual([]);
  });
  it("fires at -20% and labels the rounded deficit", () => {
    const m = lowVolMarkers(SPY_BARS, ma, { thresholdPct: -20, color: "#888" });
    const last = m.find((x) => x.time === "2026-07-10");
    expect(last).toBeDefined();
    expect(last!.text).toBe("-21%"); // vol 42,431,978 vs MA50 53,919,783.64 → -21.3%
    expect(last!.position).toBe("belowBar");
  });
});

describe("highVolMarkers", () => {
  it("labels exactly the fixture's volume peak (HVE, first bar)", () => {
    const m = highVolMarkers(SPY_BARS, { color: "#ccc" });
    expect(m).toHaveLength(1);
    expect(m[0].time).toBe("2026-03-31");
    expect(m[0].position).toBe("aboveBar");
    // text: tag + compact volume + price change% (close vs open on bar 0)
    expect(m[0].text).toBe("HVE 152.53M +1.78%");
  });
});
```

- [ ] **Step 2: Run to verify the new tests fail**

Run: `cd web && npx vitest run tests/unit/indicators.test.ts`
Expected: FAIL — `prevCloseUp` etc. not exported. Task 1 tests must still PASS.

- [ ] **Step 3: Implement (append to `web/lib/indicators.ts`)**

```ts
/** MarketSmith prevC coloring: up = close >= previous close; the first bar
 * (or a null prev close) falls back to close >= open; null close → null. */
export function prevCloseUp(
  rows: readonly IndicatorBar[],
): (boolean | null)[] {
  return rows.map((r, i) => {
    if (!fin(r.close)) return null;
    const prev = i > 0 ? rows[i - 1].close : null;
    if (fin(prev)) return r.close >= prev;
    return fin(r.open) ? r.close >= r.open : true;
  });
}

/** True where the bar's volume is the minimum of the trailing `window` bars
 * (inclusive). Parity with pandas rolling(window).min(): the first window-1
 * bars are never flagged, and any null inside the window disqualifies it. */
export function lowestInWindow(
  volumes: readonly (number | null | undefined)[],
  window = 10,
): boolean[] {
  return volumes.map((v, i) => {
    if (i < window - 1 || !fin(v)) return false;
    for (let j = i - window + 1; j <= i; j++) {
      const o = volumes[j];
      if (!fin(o) || o < v) return false;
    }
    return true;
  });
}

/** Volume moving average — MarketSmith daily default 50. */
export function volumeMa(
  volumes: readonly (number | null | undefined)[],
  period = 50,
): (number | null)[] {
  return sma(volumes, period);
}

/** 42431978 → "42.43M" (K/M/B, ≤2 decimals, trailing zeros trimmed). */
export function fmtVolCompact(v: number): string {
  const units: [number, string][] = [
    [1e9, "B"],
    [1e6, "M"],
    [1e3, "K"],
  ];
  for (const [div, u] of units) {
    if (v >= div) {
      return `${parseFloat((v / div).toFixed(2))}${u}`;
    }
  }
  return String(Math.round(v));
}

export type VolMarker = {
  time: string;
  position: "aboveBar" | "belowBar";
  shape: "circle";
  color: string;
  text: string;
  size: number;
};

/** Low-relative-volume tags: volume at least |thresholdPct|% below its MA.
 * Ports the Pine modification (lwVolThreshold, default -25). */
export function lowVolMarkers(
  rows: readonly IndicatorBar[],
  ma: readonly (number | null)[],
  opts: { thresholdPct?: number; color: string },
): VolMarker[] {
  const threshold = opts.thresholdPct ?? -25;
  const out: VolMarker[] = [];
  rows.forEach((r, i) => {
    const m = ma[i];
    if (!fin(r.volume) || !fin(m) || m <= 0 || !r.as_of) return;
    const pct = (r.volume / m - 1) * 100;
    if (pct <= threshold) {
      out.push({
        time: r.as_of,
        position: "belowBar",
        shape: "circle",
        color: opts.color,
        text: `${Math.round(pct)}%`,
        size: 0, // dot suppressed; the text is the label
      });
    }
  });
  return out;
}

/** HVE (highest volume ever) / HV1 (highest in a year) labels, deduped so a
 * labeled bar must also be the max of its ±peakLen neighbors (Pine peakL=9).
 * Text: "HVE 152.53M +1.78%" — compact volume + that bar's price change. */
export function highVolMarkers(
  rows: readonly IndicatorBar[],
  opts: { oneYear?: number; peakLen?: number; color: string },
): VolMarker[] {
  const oneYear = opts.oneYear ?? 252;
  const peakLen = opts.peakLen ?? 9;
  const vols = rows.map((r) => r.volume);
  const out: VolMarker[] = [];
  let runningMax = -Infinity;
  rows.forEach((r, i) => {
    const v = vols[i];
    if (!fin(v) || !r.as_of) {
      return;
    }
    const isHve = v > runningMax;
    runningMax = Math.max(runningMax, v);
    // highest of the trailing year (inclusive), only meaningful when not HVE
    let isHv1 = false;
    if (!isHve) {
      isHv1 = true;
      for (let j = Math.max(0, i - oneYear + 1); j < i; j++) {
        const o = vols[j];
        if (fin(o) && o > v) {
          isHv1 = false;
          break;
        }
      }
    }
    if (!isHve && !isHv1) return;
    // peak dedup: must be the max of ±peakLen neighbors
    for (
      let j = Math.max(0, i - peakLen);
      j <= Math.min(rows.length - 1, i + peakLen);
      j++
    ) {
      const o = vols[j];
      if (j !== i && fin(o) && o > v) return;
    }
    const prev = i > 0 ? rows[i - 1].close : null;
    const base = fin(prev) ? prev : fin(r.open) ? r.open : null;
    const chg =
      fin(r.close) && fin(base) && base !== 0
        ? ` ${r.close >= base ? "+" : ""}${(((r.close as number) / (base as number) - 1) * 100).toFixed(2)}%`
        : "";
    out.push({
      time: r.as_of,
      position: "aboveBar",
      shape: "circle",
      color: opts.color,
      text: `${isHve ? "HVE" : "HV1"} ${fmtVolCompact(v)}${chg}`,
      size: 0,
    });
  });
  return out;
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd web && npx vitest run tests/unit/indicators.test.ts`
Expected: PASS, all describes. The `highVolMarkers` test proves the dedup: only 2026-03-31 is labeled (every later bar's trailing-year max includes bar 0's 152.5M, so nothing else qualifies).

- [ ] **Step 5: Typecheck and commit**

```bash
cd web && npm run typecheck
git add web/lib/indicators.ts web/tests/unit/indicators.test.ts
git commit -m "feat(web): MarketSmith volume analytics (prevC direction, low-vol, HVE/HV1, MA)"
```

---

### Task 3: Chart data transforms (`priceChartData.ts`)

**Files:**
- Modify: `web/lib/priceChartData.ts`
- Test: `web/tests/unit/priceChartData.test.ts` (existing — extend + update)

**Interfaces:**
- Consumes: `ema`, `bollinger`, `prevCloseUp`, `lowestInWindow`, `volumeMa` from Tasks 1–2; `BandPoint` from `@/lib/lwc/bandsIndicator`.
- Produces (Task 4/5 import these):
  - `toVolumeData(rows, upColor: string, downColor: string, opts?: { lowColor?: string; lowWindow?: number; truncateAt?: readonly (number | null)[] })` — **signature change**: coloring switches from close-vs-open to prev-close; optional low-vol graying and per-bar display cap.
  - `toEmaLineData(rows: readonly SeriesRow[], period: number): (LineData<Time> | WhitespaceData<Time>)[]`
  - `toBollingerBandData(rows: readonly SeriesRow[], period?: number, mult?: number): BandPoint[]`
  - `toVolumeMaData(rows: readonly SeriesRow[], period?: number): (LineData<Time> | WhitespaceData<Time>)[]`

- [ ] **Step 1: Write/adjust the failing tests**

In `web/tests/unit/priceChartData.test.ts`, add (imports at top of file; reuse the existing style):

```ts
import { toBollingerBandData, toEmaLineData, toVolumeData, toVolumeMaData } from "@/lib/priceChartData";
import { SPY_BARS } from "./fixtures/spyBars";

describe("toVolumeData (prev-close coloring)", () => {
  const rows = SPY_BARS.map((b) => ({ ...b }));
  it("colors 2026-07-08 as DOWN despite a green candle (close < prev close)", () => {
    const out = toVolumeData(rows, "#0f0", "#f00");
    const bar = out[67] as { color?: string };
    expect(rows[67].as_of).toBe("2026-07-08");
    expect(bar.color).toBe("#f00");
  });
  it("grays lowest-in-10 bars when lowColor is given", () => {
    const out = toVolumeData(rows, "#0f0", "#f00", { lowColor: "#888" });
    const idx = rows.findIndex((r) => r.as_of === "2026-07-09");
    expect((out[idx] as { color?: string }).color).toBe("#888");
  });
  it("caps displayed value at truncateAt while keeping time alignment", () => {
    const cap = rows.map(() => 50_000_000 as number | null);
    const out = toVolumeData(rows, "#0f0", "#f00", { truncateAt: cap });
    expect((out[0] as { value?: number }).value).toBe(50_000_000); // 152.5M capped
  });
});

describe("toEmaLineData / toBollingerBandData / toVolumeMaData", () => {
  const rows = SPY_BARS.map((b) => ({ ...b }));
  it("ema5 last point matches the frozen pandas value", () => {
    const out = toEmaLineData(rows, 5);
    const last = out[out.length - 1] as { value?: number };
    expect(last.value).toBeCloseTo(750.2677023210776, 8);
  });
  it("bollinger emits only converged points with frozen bounds at the tail", () => {
    const bb = toBollingerBandData(rows);
    expect(bb.length).toBe(SPY_BARS.length - 19); // first 19 bars warmup
    expect(bb[bb.length - 1].upper).toBeCloseTo(758.1623930384142, 6);
    expect(bb[bb.length - 1].lower).toBeCloseTo(729.4606069615859, 6);
  });
  it("volume MA50 last point matches the frozen pandas value", () => {
    const out = toVolumeMaData(rows, 50);
    const last = out[out.length - 1] as { value?: number };
    expect(last.value).toBeCloseTo(53919783.64, 2);
  });
});
```

Then reconcile any EXISTING `toVolumeData` tests in that file: the old close-vs-open expectation is superseded by prev-close semantics. Update those assertions to the new rule (do not delete the null-volume/whitespace cases — keep them passing).

- [ ] **Step 2: Run to verify failure**

Run: `cd web && npx vitest run tests/unit/priceChartData.test.ts`
Expected: FAIL — new exports missing; possibly old coloring assertions failing (they'll be updated as part of this task).

- [ ] **Step 3: Implement in `web/lib/priceChartData.ts`**

Replace the existing `toVolumeData` and append the new transforms:

```ts
import {
  bollinger,
  ema,
  lowestInWindow,
  prevCloseUp,
  volumeMa,
} from "@/lib/indicators";

// MarketSmith volume treatment: direction by PREVIOUS close (not bar
// direction), optional graying of lowest-in-window bars, optional display cap
// (2×MA truncation) — the hover readout still shows the true volume.
export function toVolumeData(
  rows: readonly SeriesRow[],
  upColor: string,
  downColor: string,
  opts?: {
    lowColor?: string;
    lowWindow?: number;
    truncateAt?: readonly (number | null)[];
  },
): (HistogramData<Time> | WhitespaceData<Time>)[] {
  const up = prevCloseUp(rows);
  const low = opts?.lowColor
    ? lowestInWindow(
        rows.map((r) => r.volume),
        opts.lowWindow ?? 10,
      )
    : null;
  return rows.map((r, i) => {
    const t = r.as_of as Time;
    if (r.volume == null) return { time: t };
    const cap = opts?.truncateAt?.[i];
    const value = cap != null ? Math.min(r.volume, cap) : r.volume;
    const color = low?.[i]
      ? (opts!.lowColor as string)
      : (up[i] ?? true)
        ? upColor
        : downColor;
    return { time: t, value, color };
  });
}

export function toEmaLineData(
  rows: readonly SeriesRow[],
  period: number,
): (LineData<Time> | WhitespaceData<Time>)[] {
  const e = ema(
    rows.map((r) => r.close),
    period,
  );
  return rows.map((r, i) =>
    e[i] == null
      ? { time: r.as_of as Time }
      : { time: r.as_of as Time, value: e[i] as number },
  );
}

export function toBollingerBandData(
  rows: readonly SeriesRow[],
  period = 20,
  mult = 2,
): BandPoint[] {
  const bb = bollinger(
    rows.map((r) => r.close),
    period,
    mult,
  );
  const out: BandPoint[] = [];
  rows.forEach((r, i) => {
    const u = bb.upper[i];
    const l = bb.lower[i];
    if (u != null && l != null) {
      out.push({ time: r.as_of as Time, upper: u, lower: l });
    }
  });
  return out;
}

export function toVolumeMaData(
  rows: readonly SeriesRow[],
  period = 50,
): (LineData<Time> | WhitespaceData<Time>)[] {
  const ma = volumeMa(
    rows.map((r) => r.volume),
    period,
  );
  return rows.map((r, i) =>
    ma[i] == null
      ? { time: r.as_of as Time }
      : { time: r.as_of as Time, value: ma[i] as number },
  );
}
```

(Keep the existing imports of `HistogramData`, `LineData`, `Time`, `WhitespaceData`, `BandPoint` — they are already imported at the top of this file.)

- [ ] **Step 4: Run the full unit suite**

Run: `cd web && npm run test`
Expected: PASS — including the updated legacy `toVolumeData` assertions and ALL pre-existing suites (`vwap`, `formatters`, …). A failure anywhere outside the files you touched means a regression: stop and fix.

- [ ] **Step 5: Typecheck, lint, commit**

```bash
cd web && npm run typecheck && npm run lint
git add web/lib/priceChartData.ts web/tests/unit/priceChartData.test.ts
git commit -m "feat(web): price-pane transforms — prevC volume coloring, EMA/Bollinger/volMA data"
```

---

### Task 4: Overlay mode toggle (SMA·σ ⇄ EMA·BB) + `fullRows` threading

**Files:**
- Modify: `web/components/stock/panels/TechnicalsPriceChart.tsx`
- Modify: `web/components/stock/tabs/TechnicalsTab.tsx` (one prop)

**Interfaces:**
- Consumes: `toEmaLineData`, `toBollingerBandData` (Task 3); existing `toSmaLineData`, `toBandData`.
- Produces: `TechnicalsPriceChart` props become `{ data: TechnicalsResponse; fullRows?: SeriesRow[]; control?: ReactNode }`. `fullRows` = the UNWINDOWED series; defaults to `data.series` when absent (back-compat). Task 5 builds on the same prop.

- [ ] **Step 1: Thread `fullRows` from the tab**

In `TechnicalsTab.tsx` (~line 456), pass the unwindowed series:

```tsx
<TechnicalsPriceChart
  data={view}
  fullRows={(data.series ?? []) as SeriesRow[]}
  control={<TimeframeSelect value={timeframe} onChange={setTimeframe} />}
/>
```

(Import `type SeriesRow` from `@/lib/priceChartData` if not already imported in the tab; otherwise inline-cast as shown.)

- [ ] **Step 2: Add mode state + toggle to `TechnicalsPriceChart.tsx`**

Top-level additions (module scope):

```ts
type OverlayMode = "sma" | "ema";
const OVERLAY_MODE_KEY = "technicals:priceOverlayMode";

// ReorderableList.tsx pattern: lazy init + try/catch; client-only component
// so no hydration mismatch.
function loadOverlayMode(): OverlayMode {
  try {
    return localStorage.getItem(OVERLAY_MODE_KEY) === "ema" ? "ema" : "sma";
  } catch {
    return "sma";
  }
}
```

Component changes:

```ts
export function TechnicalsPriceChart({
  data,
  fullRows,
  control,
}: {
  data: TechnicalsResponse;
  fullRows?: SeriesRow[];
  control?: ReactNode;
}) {
  const rows = useMemo(() => (data.series ?? []) as SeriesRow[], [data.series]);
  const full = useMemo(() => fullRows ?? rows, [fullRows, rows]);
  const [mode, setMode] = useState<OverlayMode>(loadOverlayMode);
  const setModePersist = (m: OverlayMode) => {
    setMode(m);
    try {
      localStorage.setItem(OVERLAY_MODE_KEY, m);
    } catch {
      /* storage unavailable */
    }
  };
  // ... existing body
```

Rename `ChartHandles.smas` to mode-neutral keys (update the build effect and data pass accordingly):

```ts
type ChartHandles = {
  chart: IChartApi;
  price: ISeriesApi<"Candlestick"> | ISeriesApi<"Line">;
  volume: ISeriesApi<"Histogram"> | null;
  mas: Record<"fast" | "mid" | "slow", ISeriesApi<"Line">>;
  vwap: ISeriesApi<"Line">;
  bands: BandsIndicator;
};
```

In the build effect the three series keep their colors (`--accent-warm` fast, `--accent-vol` mid, `--accent-vivid` slow) — same visual weight in both modes, consistent with the page.

Data pass (the `useEffect` at ~line 276) becomes mode-aware. EMA/BB are computed over `full` then cut to the visible window (`rows[0].as_of`) so the left edge is converged:

```ts
useEffect(() => {
  const h = handlesRef.current;
  if (!h) return;
  const positive = cssVar("--positive");
  const negative = cssVar("--negative");
  const firstAsOf = rows[0]?.as_of ?? "";
  const cut = <T extends { time: Time }>(a: T[]) =>
    a.filter((p) => String(p.time) >= firstAsOf);
  if (candleMode) {
    (h.price as ISeriesApi<"Candlestick">).setData(toCandleData(rows));
    h.volume?.setData(
      cut(
        toVolumeData(full, `${positive}59`, `${negative}59`, {
          lowColor: cssVar("--text-muted"),
        }) as { time: Time }[],
      ) as ReturnType<typeof toVolumeData>,
    );
  } else {
    (h.price as ISeriesApi<"Line">).setData(toCloseLineData(rows));
  }
  if (mode === "sma") {
    h.mas.fast.setData(toSmaLineData(rows, "sma20"));
    h.mas.mid.setData(toSmaLineData(rows, "sma50"));
    h.mas.slow.setData(toSmaLineData(rows, "sma200"));
    h.bands.setBandData(toBandData(rows));
  } else {
    h.mas.fast.setData(cut(toEmaLineData(full, 5)));
    h.mas.mid.setData(cut(toEmaLineData(full, 20)));
    h.mas.slow.setData(cut(toEmaLineData(full, 50)));
    h.bands.setBandData(cut(toBollingerBandData(full)));
  }
  // ...existing vwap fill + fitContent block unchanged, except add `mode`
  // and `full` to the dependency array.
}, [rows, full, ticker, candleMode, anchor, mode]);
```

Note on `cut` typing: `toVolumeData` returns a union including `WhitespaceData<Time>` which has `time` — the filter is type-safe; if TS complains, filter before the cast: `h.volume?.setData(toVolumeData(full, ...).filter((p) => String(p.time) >= firstAsOf));` (simpler — prefer this form).

- [ ] **Step 3: Toggle UI + mode-aware title/legend**

Header control (inside the existing `header` ReactNode, before `{control}`), styled like the existing VWAP-clear button:

```tsx
<span
  role="group"
  aria-label="Overlay mode"
  style={{ display: "inline-flex", gap: 0 }}
>
  {(
    [
      ["sma", "SMA·σ"],
      ["ema", "EMA·BB"],
    ] as const
  ).map(([m, label]) => (
    <button
      key={m}
      type="button"
      onClick={() => setModePersist(m)}
      aria-pressed={mode === m}
      style={{
        fontFamily: "var(--font-mono)",
        fontSize: 10,
        letterSpacing: 1,
        color: mode === m ? "var(--text-primary)" : "var(--text-muted)",
        background:
          mode === m ? "var(--bg-panel-raised)" : "transparent",
        border: "1px solid var(--border-dim)",
        borderRadius: m === "sma" ? "4px 0 0 4px" : "0 4px 4px 0",
        marginLeft: m === "ema" ? -1 : 0,
        padding: "2px 7px",
        cursor: "pointer",
      }}
    >
      {label}
    </button>
  ))}
</span>
```

Title/subtitle (both render paths — the thin-history early return and the main one):

```ts
const title =
  mode === "sma"
    ? "Price, Moving Averages & ±1.5σ Band"
    : "Price, EMAs & Bollinger Bands";
```

Legend becomes mode-aware:

```tsx
function Legend({ mode, showVwap }: { mode: OverlayMode; showVwap: boolean }) {
  // item() helper unchanged
  const labels =
    mode === "sma"
      ? (["SMA20", "SMA50", "SMA200"] as const)
      : (["EMA5", "EMA20", "EMA50"] as const);
  return (
    <div style={{ marginTop: 6 }}>
      {item("var(--text-primary)", "PRICE")}
      {item("var(--accent-warm)", labels[0])}
      {item("var(--accent-vol)", labels[1])}
      {item("var(--accent-vivid)", labels[2])}
      {showVwap && item("var(--accent-cool)", "VWAP ⚓")}
    </div>
  );
}
```

Call site: `<Legend mode={mode} showVwap={anchor != null} />`.

- [ ] **Step 4: Verify**

```bash
cd web && npm run typecheck && npm run lint && npm run test
```
Expected: all PASS. Then a runtime check — start the local stack (`bash scripts/dev.sh` from repo root, web on :3001) and open `http://localhost:3001/stock/SPY` → Technicals tab:
- Default renders identically to before (SMA mode, title "Price, Moving Averages & ±1.5σ Band").
- Click `EMA·BB`: three MA lines re-fill (EMA5 hugs price closest), band narrows to a Bollinger envelope, title and legend flip, no console errors.
- Volume bars now colored by prev-close; the occasional muted-gray bar (lowest-in-10) appears.
- Reload the page: EMA mode persists (localStorage). Switch back to SMA before moving on.
- Switch timeframe 3M: EMA50 is present and smooth at the left edge (full-history warmup working).

- [ ] **Step 5: Commit**

```bash
git add web/components/stock/panels/TechnicalsPriceChart.tsx web/components/stock/tabs/TechnicalsTab.tsx
git commit -m "feat(web): SMA·σ ⇄ EMA·BB overlay toggle + prevC volume coloring on price pane"
```

---

### Task 5: Volume MA line, HVE/HV1 + low-vol markers, buzz readout

**Files:**
- Modify: `web/components/stock/panels/TechnicalsPriceChart.tsx`

**Interfaces:**
- Consumes: `toVolumeMaData` (Task 3); `highVolMarkers`, `lowVolMarkers`, `volumeMa`, `fmtVolCompact`, `type VolMarker` (Task 2); `createSeriesMarkers` from `lightweight-charts`.

- [ ] **Step 1: Add the volume-MA series and markers plugin to the build effect**

Extend `ChartHandles`:

```ts
import { createSeriesMarkers, type ISeriesMarkersPluginApi } from "lightweight-charts";

type ChartHandles = {
  // ...existing fields from Task 4...
  volMa: ISeriesApi<"Line"> | null;
  volMarkers: ISeriesMarkersPluginApi<Time> | null;
};
```

In the build effect, right after the volume histogram is created (candleMode block):

```ts
let volMa: ISeriesApi<"Line"> | null = null;
let volMarkers: ISeriesMarkersPluginApi<Time> | null = null;
if (candleMode && volume) {
  volMa = chart.addSeries(LineSeries, {
    color: cssVar("--warning"),
    priceScaleId: "", // same overlay scale as the volume histogram
    lineWidth: 1,
    priceLineVisible: false,
    lastValueVisible: false,
    crosshairMarkerVisible: false,
  });
  volMa.priceScale().applyOptions({ scaleMargins: { top: 0.78, bottom: 0 } });
  volMarkers = createSeriesMarkers(volume, []);
}
```

Add both to `handlesRef.current = { ... volMa, volMarkers }` and the cleanup keeps working via `chart.remove()` (removes all series; the markers plugin dies with its series — no separate detach needed on teardown).

- [ ] **Step 2: Fill MA + markers in the data pass**

Inside the `candleMode` branch of the data-pass effect (after the volume `setData`), using module-scope constants:

```ts
// MarketSmith knobs — constants, not UI (trim candidates after live review).
const VOL_MA_PERIOD = 50;
const LOW_VOL_THRESHOLD_PCT = -25;
const TRUNCATE_VOLUME_AT_2X_MA = false; // MarketSmith display style; readout shows true vol
```

```ts
const volMaFull = volumeMa(full.map((r) => r.volume), VOL_MA_PERIOD);
h.volMa?.setData(
  toVolumeMaData(full, VOL_MA_PERIOD).filter(
    (p) => String(p.time) >= firstAsOf,
  ),
);
if (h.volMarkers) {
  const muted = cssVar("--text-muted");
  const markers = [
    ...highVolMarkers(full, { color: cssVar("--text-secondary") }),
    ...lowVolMarkers(full, volMaFull, {
      thresholdPct: LOW_VOL_THRESHOLD_PCT,
      color: muted,
    }),
  ]
    .filter((m) => m.time >= firstAsOf)
    .sort((a, b) => (a.time < b.time ? -1 : a.time > b.time ? 1 : 0));
  h.volMarkers.setMarkers(
    markers.map((m) => ({ ...m, time: m.time as Time })),
  );
}
```

And wire the truncation constant into the volume fill from Task 4:

```ts
h.volume?.setData(
  toVolumeData(full, `${positive}59`, `${negative}59`, {
    lowColor: cssVar("--text-muted"),
    truncateAt: TRUNCATE_VOLUME_AT_2X_MA
      ? volMaFull.map((m) => (m == null ? null : 2 * m))
      : undefined,
  }).filter((p) => String(p.time) >= firstAsOf),
);
```

- [ ] **Step 3: Buzz readout (hover + default last-bar)**

The readout currently shows `date O H L C V` on hover and empty otherwise. Change: append `· NN.N M · X.XX×MA50` when the bar has volume and an MA value, and show the LAST bar's line by default instead of empty. Keep a lookup from the data pass:

```ts
// in component scope
const volMaByTimeRef = useRef<Map<string, number>>(new Map());
```

Populate in the data pass (candleMode branch):

```ts
volMaByTimeRef.current = new Map(
  full.flatMap((r, i) =>
    volMaFull[i] != null ? [[r.as_of, volMaFull[i] as number]] : [],
  ),
);
```

Extract a formatter used by both hover and default paths (module scope):

```ts
function readoutLine(
  time: string,
  bar: { open?: number; high?: number; low?: number; close?: number; value?: number },
  vol: number | null | undefined,
  volMa: number | undefined,
): string {
  const f = (x?: number) => (x == null ? "–" : x.toFixed(2));
  const buzz =
    vol != null
      ? `  V ${fmtVolCompact(vol)}${volMa ? ` · ${(vol / volMa).toFixed(2)}×MA50` : ""}`
      : "";
  return bar.open != null
    ? `${time}  O ${f(bar.open)} H ${f(bar.high)} L ${f(bar.low)} C ${f(bar.close)}${buzz}`
    : `${time}  C ${f(bar.value)}${buzz}`;
}
```

Hover handler (`onMove`) switches to `readoutLine(...)` — note it must read the TRUE volume from `rowsRef.current` (not the possibly truncated histogram value):

```ts
const t = String(param.time);
const row = rowsRef.current.find((r) => r.as_of === t);
out.textContent = bar
  ? readoutLine(t, bar, row?.volume, volMaByTimeRef.current.get(t))
  : "";
```

Default (no hover) — at the end of the data pass, when the readout is empty, write the last bar's line:

```ts
const lastRow = rows[rows.length - 1];
if (readoutRef.current && lastRow?.as_of) {
  readoutRef.current.textContent = readoutLine(
    lastRow.as_of,
    { open: lastRow.open ?? undefined, high: lastRow.high ?? undefined,
      low: lastRow.low ?? undefined, close: lastRow.close ?? undefined,
      value: lastRow.close ?? undefined },
    lastRow.volume,
    volMaByTimeRef.current.get(lastRow.as_of),
  );
}
```

And the crosshair-leave branch of `onMove` (no point/time) restores the last-bar line instead of clearing to empty (same call with the last row of `rowsRef.current`).

- [ ] **Step 4: Verify**

```bash
cd web && npm run typecheck && npm run lint && npm run test
```
Expected: PASS. Runtime check on `http://localhost:3001/stock/SPY` → Technicals:
- Volume MA50 line (warning color) rides the histogram; readout shows e.g. `2026-07-10  O … C …  V 42.43M · 0.79×MA50` by default (no hover).
- Hovering any bar updates the line; leaving the chart restores the last-bar line.
- Low-volume bars carry a small `-NN%` label below; a volume spike bar (if in window) carries `HVE …`/`HV1 …` above.
- Zoom/pan still works; VWAP click-to-anchor still works (click a bar → anchored line appears).
- Check a SECOND ticker with shorter history (e.g. a recently added watchlist name) for the close-only path: volume features absent, no errors.

- [ ] **Step 5: Commit**

```bash
git add web/components/stock/panels/TechnicalsPriceChart.tsx
git commit -m "feat(web): volume MA50 + HVE/HV1 & low-vol markers + buzz readout on price pane"
```

---

### Task 6: E2E smoke, CHANGELOG, full gate

**Files:**
- Modify: `web/tests/e2e/technicals-tab.spec.ts`
- Modify: `CHANGELOG.md`

- [ ] **Step 1: Extend the existing e2e spec**

`web/tests/e2e/technicals-tab.spec.ts` already smoke-tests `/stock/DRYRUN/technicals` (renders either panels or the honest empty state, no NaN, no console errors). Add a toggle test in the same file, same conventions:

```ts
test("overlay toggle flips SMA/EMA legend without console errors", async ({
  page,
}) => {
  const consoleErrors: string[] = [];
  page.on("console", (msg) => {
    if (msg.type() === "error") consoleErrors.push(msg.text());
  });
  await page.goto(`/stock/${TICKER}/technicals`);
  const toggle = page.getByRole("button", { name: "EMA·BB" });
  // Toggle only exists when the price pane rendered (i.e. history present);
  // on the empty state this test degrades to the render smoke.
  if (await toggle.isVisible().catch(() => false)) {
    // Assert on "EMA5" only — unique to the price-pane legend; "SMA20" also
    // appears in detail tiles and would trip Playwright strict mode.
    await toggle.click();
    await expect(page.getByText("EMA5", { exact: true })).toBeVisible();
    await page.getByRole("button", { name: "SMA·σ" }).click();
    await expect(page.getByText("EMA5", { exact: true })).not.toBeVisible();
  }
  expect(consoleErrors).toHaveLength(0);
});
```

- [ ] **Step 2: CHANGELOG entry**

Add under `## [Unreleased]` in `CHANGELOG.md` (create the section if absent, matching the file's existing entry style):

```markdown
- Technicals price pane: MarketSmith volume treatment (previous-close coloring,
  volume MA50 line, low-relative-volume graying and −% labels, HVE/HV1 peak
  labels, volume buzz readout) and a small SMA·σ ⇄ EMA·BB overlay toggle
  (SMA20/50/200 + ±1.5σ band ⇄ EMA5/20/50 + Bollinger 20,2), computed
  client-side over the full series. Frontend-only.
```

- [ ] **Step 3: Full local gate**

```bash
cd web && npm run typecheck && npm run lint && npm run test
```
Expected: all PASS, zero skips in the files this branch touched.

```bash
cd web && npx playwright test tests/e2e/technicals-tab.spec.ts
```
Expected: PASS (requires the dev stack running: `bash scripts/dev.sh` from repo root). If the harness needs a base URL, follow the existing playwright config — do not invent flags.

- [ ] **Step 4: Final review sweep**

- `git diff main --stat` — confirm ONLY these files changed: `web/lib/indicators.ts`, `web/lib/priceChartData.ts`, `web/components/stock/panels/TechnicalsPriceChart.tsx`, `web/components/stock/tabs/TechnicalsTab.tsx`, `web/tests/unit/indicators.test.ts`, `web/tests/unit/priceChartData.test.ts`, `web/tests/unit/fixtures/spyBars.ts`, `web/tests/e2e/technicals-tab.spec.ts`, `CHANGELOG.md`, plus the spec/plan docs. Anything else = scope leak, investigate.
- Grep guard: `grep -rn "lightweight-charts" web/components --include="*.tsx" | grep -v TechnicalsPriceChart` must return nothing (library stays confined to the price pane).
- Confirm no expected-value constant in the tests was modified relative to this plan (`git diff` the test files against the code blocks above if in doubt).

- [ ] **Step 5: Commit and stop**

```bash
git add web/tests/e2e/technicals-tab.spec.ts CHANGELOG.md
git commit -m "test(web): technicals overlay-toggle e2e + changelog"
```

Do NOT push or open a PR — report back for human review first (screenshots of the pane in both modes via the running dev stack are the expected evidence, saved under `output/playwright/`).
