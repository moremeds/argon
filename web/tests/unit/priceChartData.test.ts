import { describe, expect, it } from "vitest";
import {
  hasOhlcv,
  toBandData,
  toCandleData,
  toVolumeData,
} from "@/lib/priceChartData";

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
  it("hasOhlcv detects any OHLC-bearing row", () => {
    expect(hasOhlcv([full, closeOnly])).toBe(true);
    expect(hasOhlcv([closeOnly, empty])).toBe(false);
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

  it("toVolumeData colors by candle direction, whitespace when null", () => {
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

  it("toBandData recovers the ±1.5σ envelope from stored z (half = 1.5·(c−m)/z)", () => {
    const r = { as_of: "2026-07-06", close: 110, sma200: 100, z: 2 };
    // sigma = (c-m)/z = 5 -> half = 7.5
    expect(toBandData([r] as never[])).toEqual([
      { time: "2026-07-06", upper: 107.5, lower: 92.5 },
    ]);
    expect(
      toBandData([{ as_of: "x", close: 110, sma200: 100, z: 0 }] as never[]),
    ).toEqual([]);
  });
});
