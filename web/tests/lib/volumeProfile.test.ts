import { describe, expect, it } from "vitest";
import { computeVolumeProfile, type VpBar } from "@/lib/volumeProfile";
import { SPY_BARS } from "../unit/fixtures/spyBars";

const bars: VpBar[] = SPY_BARS.map((b) => ({
  open: b.open,
  high: b.high,
  low: b.low,
  close: b.close,
  volume: b.volume,
}));

describe("computeVolumeProfile on real SPY daily bars", () => {
  const p = computeVolumeProfile(bars, 60, 70)!;

  it("returns a profile", () => {
    expect(p).not.toBeNull();
    expect(p.bins).toHaveLength(60);
  });

  it("bins tile the full high/low range contiguously and ascending", () => {
    const hi = Math.max(...bars.map((b) => b.high));
    const lo = Math.min(...bars.map((b) => b.low));
    expect(p.bins[0].low).toBeCloseTo(lo, 6);
    expect(p.bins[59].high).toBeCloseTo(hi, 6);
    for (let i = 1; i < p.bins.length; i += 1) {
      expect(p.bins[i].low, `bin ${i} starts where ${i - 1} ends`).toBeCloseTo(
        p.bins[i - 1].high,
        6,
      );
    }
  });

  it("conserves total volume across the bins", () => {
    const total = p.bins.reduce((a, b) => a + b.buy + b.sell, 0);
    const expected = bars.reduce((a, b) => a + b.volume, 0);
    expect(total).toBeCloseTo(expected, 0);
  });

  it("POC is the richest bin and its price sits inside it", () => {
    const vol = (i: number) => p.bins[i].buy + p.bins[i].sell;
    for (let i = 0; i < p.bins.length; i += 1) {
      expect(vol(i)).toBeLessThanOrEqual(vol(p.pocIdx));
    }
    expect(p.maxBinVolume).toBeCloseTo(vol(p.pocIdx), 6);
    expect(p.pocPrice).toBeGreaterThan(p.bins[p.pocIdx].low);
    expect(p.pocPrice).toBeLessThan(p.bins[p.pocIdx].high);
  });

  it("value area brackets the POC and holds >= 70% of volume", () => {
    expect(p.valIdx).toBeLessThanOrEqual(p.pocIdx);
    expect(p.vahIdx).toBeGreaterThanOrEqual(p.pocIdx);
    const total = p.bins.reduce((a, b) => a + b.buy + b.sell, 0);
    const inVa = p.bins
      .slice(p.valIdx, p.vahIdx + 1)
      .reduce((a, b) => a + b.buy + b.sell, 0);
    expect(inVa / total).toBeGreaterThanOrEqual(0.7);
    // ...and it is minimal: dropping either edge falls below the target.
    const withoutEdge =
      inVa -
      Math.min(
        p.bins[p.valIdx].buy + p.bins[p.valIdx].sell,
        p.bins[p.vahIdx].buy + p.bins[p.vahIdx].sell,
      );
    expect(withoutEdge / total).toBeLessThan(0.7);
  });

  it("splits buy/sell by the bar's own close vs open", () => {
    const upVol = bars
      .filter((b) => b.close >= b.open)
      .reduce((a, b) => a + b.volume, 0);
    expect(p.bins.reduce((a, b) => a + b.buy, 0)).toBeCloseTo(upVol, 0);
  });

  it("is deterministic", () => {
    expect(computeVolumeProfile(bars, 60, 70)).toEqual(p);
  });

  it("returns null on degenerate input", () => {
    expect(computeVolumeProfile([], 60)).toBeNull();
    expect(computeVolumeProfile(bars.slice(0, 1), 60)).toBeNull();
    const flat = [
      { open: 5, high: 5, low: 5, close: 5, volume: 100 },
      { open: 5, high: 5, low: 5, close: 5, volume: 100 },
    ];
    expect(computeVolumeProfile(flat, 60), "zero-width range").toBeNull();
    expect(
      computeVolumeProfile(
        bars.map((b) => ({ ...b, volume: 0 })),
        60,
      ),
      "no volume anywhere",
    ).toBeNull();
  });
});
