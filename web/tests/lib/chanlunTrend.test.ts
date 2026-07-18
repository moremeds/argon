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
