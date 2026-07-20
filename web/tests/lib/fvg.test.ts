import { describe, expect, it } from "vitest";
import { findFairValueGaps, type FvgBar } from "@/lib/fvg";
import { SPY_BARS } from "../unit/fixtures/spyBars";

const bar = (time: string, low: number, high: number): FvgBar => ({
  time,
  low,
  high,
});

describe("findFairValueGaps", () => {
  it("finds a bullish gap and reports the untraded band", () => {
    const gaps = findFairValueGaps([
      bar("d1", 10, 11),
      bar("d2", 11, 15),
      bar("d3", 13, 16), // low 13 > d1 high 11 → gap 11..13
    ]);
    expect(gaps).toEqual([{ time: "d2", top: 13, bottom: 11, bullish: true }]);
  });

  it("finds a bearish gap", () => {
    const gaps = findFairValueGaps([
      bar("d1", 20, 21),
      bar("d2", 15, 20),
      bar("d3", 14, 17), // high 17 < d1 low 20 → gap 17..20
    ]);
    expect(gaps).toEqual([{ time: "d2", top: 20, bottom: 17, bullish: false }]);
  });

  it("drops a gap once a later bar trades back into it", () => {
    const withFill = [
      bar("d1", 10, 11),
      bar("d2", 11, 15),
      bar("d3", 13, 16),
      bar("d4", 11.5, 14), // dips to 11.5, inside the 11..13 band
    ];
    expect(findFairValueGaps(withFill)).toEqual([]);
    // ...but a bar that stops short of the band leaves it open.
    const noFill = [...withFill.slice(0, 3), bar("d4", 13.5, 16)];
    expect(findFairValueGaps(noFill)).toHaveLength(1);
  });

  it("returns oldest first and honours maxCount by keeping the newest", () => {
    const seq: FvgBar[] = [];
    // Staircase up: every middle bar leaves an unfilled bullish gap.
    // Zero-padded: "d10" sorts before "d2" as a string otherwise.
    for (let i = 0; i < 12; i += 1) {
      seq.push(bar(`d${String(i).padStart(2, "0")}`, 10 + i * 10, 12 + i * 10));
    }
    const all = findFairValueGaps(seq, 100);
    expect(all.length).toBeGreaterThan(3);
    for (let i = 1; i < all.length; i += 1) {
      expect(all[i].time > all[i - 1].time).toBe(true);
    }
    const capped = findFairValueGaps(seq, 3);
    expect(capped).toHaveLength(3);
    expect(capped).toEqual(all.slice(-3));
  });

  it("needs three bars", () => {
    expect(findFairValueGaps([bar("d1", 1, 2), bar("d2", 5, 6)])).toEqual([]);
  });

  it("returns only unfilled gaps on real SPY bars", () => {
    const spy: FvgBar[] = SPY_BARS.map((b) => ({
      time: b.as_of,
      high: b.high,
      low: b.low,
    }));
    const gaps = findFairValueGaps(spy, 20);
    for (const g of gaps) {
      expect(g.top).toBeGreaterThan(g.bottom);
      const after = spy.slice(spy.findIndex((b) => b.time === g.time) + 2);
      for (const b of after) {
        const reentered = b.low < g.top && b.high > g.bottom;
        expect(reentered, `gap at ${g.time} was filled on ${b.time}`).toBe(
          false,
        );
      }
    }
  });
});
