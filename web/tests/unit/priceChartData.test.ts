import { describe, expect, it, vi } from "vitest";
import {
  hasOhlcv,
  toAtrBandData,
  toBollingerBandData,
  toCandleData,
  toEmaLineData,
  toVolumeData,
  toVolumeMaData,
} from "@/lib/priceChartData";
import {
  resetView,
  TECHNICALS_TIME_SCALE_OPTIONS,
  VOLUME_MARKER_OPTIONS,
} from "@/components/stock/panels/TechnicalsPriceChart";
import { SPY_BARS } from "./fixtures/spyBars";

const full = {
  as_of: "2026-07-06",
  open: 9,
  high: 10,
  low: 8,
  close: 9.5,
  volume: 100,
};
const closeOnly = { as_of: "2026-07-07", close: 9.8 };
const empty = { as_of: "2026-07-08" };

describe("priceChartData", () => {
  it("hasOhlcv requires a majority of rows to carry OHLC", () => {
    expect(hasOhlcv([full, closeOnly])).toBe(true); // 50% -> candle mode
    expect(hasOhlcv([closeOnly, empty])).toBe(false);
    // one OHLC forming head on a close-only history stays in LINE mode, so the
    // history doesn't render as a wall of flat dojis before backfill lands.
    expect(hasOhlcv([closeOnly, closeOnly, full])).toBe(false);
    expect(hasOhlcv([])).toBe(false);
  });

  it("toCandleData: full candle / flat tick for close-only / whitespace", () => {
    const [a, b, c] = toCandleData([full, closeOnly, empty] as never[]);
    expect(a).toEqual({
      time: "2026-07-06",
      open: 9,
      high: 10,
      low: 8,
      close: 9.5,
    });
    expect(b).toEqual({
      time: "2026-07-07",
      open: 9.8,
      high: 9.8,
      low: 9.8,
      close: 9.8,
    });
    expect(c).toEqual({ time: "2026-07-08" });
  });

  it("toVolumeData colors by previous close, whitespace when null", () => {
    // idx0 full: no prev close -> close>=open fallback (9.5>=9) -> UP
    // idx1 down: prev close 9.5, close 9 -> 9>=9.5 false -> DN
    // idx2 closeOnly: no volume -> whitespace
    const down = { ...full, as_of: "2026-07-09", open: 10, close: 9 };
    const [a, b, c] = toVolumeData(
      [full, down, closeOnly] as never[],
      "UP",
      "DN",
    );
    expect(a).toEqual({ time: "2026-07-06", value: 100, color: "UP" });
    expect(b).toEqual({ time: "2026-07-09", value: 100, color: "DN" });
    expect(c).toEqual({ time: "2026-07-07" }); // no volume -> whitespace
  });

  it("toAtrBandData: sma20 ±2·ATR14, one entry per row, warm-up as gap points", () => {
    // constant H/L/C -> every true range is 2, so ATR14 = 2 from bar 13 on.
    const bars = Array.from({ length: 15 }, (_, i) => ({
      as_of: `d${i}`,
      high: 10,
      low: 8,
      close: 9,
      sma20: 100,
    }));
    const out = toAtrBandData(bars as never[]);
    expect(out).toHaveLength(15); // never omits a row, even during warm-up
    expect(out.slice(0, 13)).toEqual(
      Array.from({ length: 13 }, (_, i) => ({ time: `d${i}` })),
    );
    expect(out[13]).toEqual({ time: "d13", upper: 104, lower: 96 });
    expect(out[14]).toEqual({ time: "d14", upper: 104, lower: 96 });
    // too short to ever finish warm-up -> every entry is a gap point
    expect(toAtrBandData(bars.slice(0, 13) as never[])).toEqual(
      Array.from({ length: 13 }, (_, i) => ({ time: `d${i}` })),
    );
  });
});

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

describe("toVolumeData (extreme-highlight shading)", () => {
  const alphaOf = (c?: string) => parseInt((c ?? "").slice(7, 9), 16);
  // Three up-days (green), MA=100. buzz 2.0 (extreme high), 1.0 (in line with
  // MA — normal), 0.5 (extreme low). Both tails should pop over the normal bar.
  const rows = [
    { as_of: "2026-01-02", open: 1, high: 2, low: 1, close: 2, volume: 200 },
    { as_of: "2026-01-05", open: 1, high: 2, low: 1, close: 2, volume: 100 },
    { as_of: "2026-01-06", open: 1, high: 2, low: 1, close: 2, volume: 50 },
  ];

  it("highlights both tails: extreme-high and extreme-low pop over a normal bar", () => {
    const out = toVolumeData(rows as never[], "#00ff00", "#ff0000", {
      magnitude: [100, 100, 100],
    });
    const [hi, mid, lo] = out.map((p) =>
      alphaOf((p as { color?: string }).color),
    );
    for (const p of out) {
      expect((p as { color?: string }).color?.slice(0, 7)).toBe("#00ff00"); // hue preserved
    }
    expect(hi).toBe(255); // ≥2×MA → fully opaque
    expect(hi).toBeGreaterThan(mid); // extreme high pops over the normal bar
    expect(lo).toBeGreaterThan(mid); // extreme LOW pops over the normal bar too
  });

  it("omits the alpha suffix entirely when no magnitude is given", () => {
    const out = toVolumeData(rows as never[], "#00ff00", "#ff0000");
    expect((out[0] as { color?: string }).color).toBe("#00ff00"); // 6-digit, no AA
  });
});

describe("volume annotation scaling", () => {
  it("does not let hover labels change the volume scale", () => {
    expect(VOLUME_MARKER_OPTIONS).toEqual({ autoScale: false });
  });
});

describe("technicals chart reset view", () => {
  it("allows the configured right offset to extend beyond the latest bar", () => {
    expect(TECHNICALS_TIME_SCALE_OPTIONS).toMatchObject({
      rightOffset: 10,
      fixRightEdge: false,
    });
  });

  function chartHandles(width: number) {
    const timeScale = {
      width: vi.fn(() => width),
      applyOptions: vi.fn(),
      scrollToPosition: vi.fn(),
      setVisibleLogicalRange: vi.fn(),
    };
    return {
      handles: { chart: { timeScale: () => timeScale } } as never,
      timeScale,
    };
  }

  it("leaves ten bar-widths after the latest bar for a long history", () => {
    const { handles, timeScale } = chartHandles(500);

    resetView(handles, 100);

    expect(timeScale.applyOptions).toHaveBeenCalledWith({ barSpacing: 6 });
    expect(timeScale.scrollToPosition).toHaveBeenCalledWith(10, false);
  });

  it("counts the right gap when enforcing readable bar spacing", () => {
    const { handles, timeScale } = chartHandles(600);

    resetView(handles, 100);

    expect(timeScale.applyOptions).toHaveBeenCalledWith({ barSpacing: 6 });
    expect(timeScale.scrollToPosition).toHaveBeenCalledWith(10, false);
    expect(timeScale.setVisibleLogicalRange).not.toHaveBeenCalled();
  });

  it("leaves ten logical bars after the latest bar for a short history", () => {
    const { handles, timeScale } = chartHandles(800);

    resetView(handles, 100);

    expect(timeScale.setVisibleLogicalRange).toHaveBeenCalledWith({
      from: 0,
      to: 109,
    });
  });
});

describe("toEmaLineData / toBollingerBandData / toVolumeMaData", () => {
  const rows = SPY_BARS.map((b) => ({ ...b }));
  it("ema5 last point matches the frozen pandas value", () => {
    const out = toEmaLineData(rows, 5);
    const last = out[out.length - 1] as { value?: number };
    expect(last.value).toBeCloseTo(750.2677023210776, 8);
  });
  it("bollinger emits a gap point per warm-up bar, converged bounds at the tail", () => {
    const bb = toBollingerBandData(rows);
    expect(bb).toHaveLength(SPY_BARS.length); // one entry per row, never omitted
    const warmup = bb.slice(0, 19); // first 19 bars warmup
    expect(warmup.every((p) => !("upper" in p))).toBe(true);
    const last = bb[bb.length - 1] as { upper: number; lower: number };
    expect(last.upper).toBeCloseTo(758.1623930384142, 6);
    expect(last.lower).toBeCloseTo(729.4606069615859, 6);
  });
  it("degenerate zero-width Bollinger points render as gaps, not omitted rows", () => {
    const rows = Array.from({ length: 20 }, (_, i) => ({
      as_of: `2026-01-${String(i + 1).padStart(2, "0")}`,
      close: 100,
    }));
    const out = toBollingerBandData(rows);
    expect(out).toHaveLength(20);
    expect(out.every((p) => !("upper" in p))).toBe(true);
  });
  it("volume MA50 last point matches the frozen pandas value", () => {
    const out = toVolumeMaData(rows, 50);
    const last = out[out.length - 1] as { value?: number };
    expect(last.value).toBeCloseTo(53919783.64, 2);
  });
});
