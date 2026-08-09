import { describe, expect, it } from "vitest";
import {
  computeVolumeProfile,
  countRetests,
  findLvnLevels,
  findSrZones,
  RECENT_BARS,
  type VpBar,
} from "@/lib/volumeProfile";
import { binJitter } from "@/lib/lwc/volumeProfile";
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

describe("countRetests", () => {
  const band = (...ranges: [number, number][]) =>
    ranges.map(([low, high]) => ({ low, high }));

  it("counts one entry per excursion, not per bar inside", () => {
    // in, in, out, in  →  two distinct entries
    const bars = band([99, 101], [99, 101], [90, 92], [99, 101]);
    expect(countRetests(bars, 100, 1)).toBe(2);
  });

  it("counts nothing when price never reaches the band", () => {
    expect(countRetests(band([90, 92], [88, 91]), 100, 1)).toBe(0);
  });

  it("counts a bar that straddles the band", () => {
    expect(countRetests(band([80, 120]), 100, 1)).toBe(1);
  });
});

describe("findSrZones on real SPY daily bars", () => {
  const profile = computeVolumeProfile(bars, 60, 70)!;
  const refPrice = bars[bars.length - 1].close;
  const zones = findSrZones(profile, bars, refPrice);

  it("classifies side by the reference price", () => {
    for (const z of zones) {
      if (z.side === "support") expect(z.price).toBeLessThan(refPrice);
      else expect(z.price).toBeGreaterThanOrEqual(refPrice);
    }
  });

  it("respects the per-side cap", () => {
    const caps = findSrZones(profile, bars, refPrice, { maxPerSide: 2 });
    expect(caps.filter((z) => z.side === "support").length).toBeLessThanOrEqual(
      2,
    );
    expect(
      caps.filter((z) => z.side === "resistance").length,
    ).toBeLessThanOrEqual(2);
  });

  it("never returns overlapping bands", () => {
    const sorted = [...zones].sort((a, b) => a.price - b.price);
    for (let i = 1; i < sorted.length; i += 1) {
      const gap = sorted[i].price - sorted[i - 1].price;
      const thickness = sorted[i].halfWidth + sorted[i - 1].halfWidth;
      expect(gap, `zones ${i - 1}/${i} overlap`).toBeGreaterThan(thickness);
    }
  });

  it("honours the strength floor and reports strength as % of POC", () => {
    for (const z of zones) {
      expect(z.strength).toBeGreaterThanOrEqual(45);
      expect(z.strength).toBeLessThanOrEqual(100);
    }
    const strict = findSrZones(profile, bars, refPrice, {
      minStrengthPct: 95,
    });
    expect(strict.length).toBeLessThanOrEqual(zones.length);
  });

  it("counts at least one retest per zone — a shelf is where price sat", () => {
    for (const z of zones) expect(z.touches).toBeGreaterThan(0);
  });

  it("is deterministic", () => {
    expect(findSrZones(profile, bars, refPrice)).toEqual(zones);
  });
});

describe("findLvnLevels", () => {
  const profile = computeVolumeProfile(bars, 60, 70)!;

  it("returns only thin bins, capped and inside the range", () => {
    const lvns = findLvnLevels(profile, bars[bars.length - 1].close);
    expect(lvns.length).toBeLessThanOrEqual(5);
    for (const price of lvns) {
      const bin = profile.bins.find((b) => b.low <= price && price <= b.high)!;
      expect(bin.buy + bin.sell).toBeLessThan(profile.maxBinVolume * 0.25);
      expect(price).toBeGreaterThanOrEqual(profile.bins[0].low);
      expect(price).toBeLessThanOrEqual(profile.bins[59].high);
    }
  });

  it("does not blow up when the reference price is off the profile", () => {
    expect(() => findLvnLevels(profile, 1e9)).not.toThrow();
    expect(() => findLvnLevels(profile, 0)).not.toThrow();
  });
});

describe("binJitter", () => {
  it("is deterministic for a given bin and dot index", () => {
    expect(binJitter(7, 3)).toBe(binJitter(7, 3));
  });

  it("differs across bins so the cloud does not look striped", () => {
    expect(binJitter(7, 3)).not.toBe(binJitter(8, 3));
  });

  it("differs across dots within a bin", () => {
    expect(binJitter(7, 3)).not.toBe(binJitter(7, 4));
  });

  it("stays within the unit interval", () => {
    for (let b = 0; b < 50; b++)
      for (let d = 0; d < 10; d++) {
        expect(binJitter(b, d)).toBeGreaterThanOrEqual(0);
        expect(binJitter(b, d)).toBeLessThan(1);
      }
  });
});

describe("VpBin.recent", () => {
  const profile = computeVolumeProfile(bars, 60, 70)!;

  it("never exceeds the bin's own total", () => {
    for (const b of profile.bins) {
      expect(b.recent).toBeLessThanOrEqual(b.buy + b.sell + 1e-6);
    }
  });

  it("sums to exactly the last RECENT_BARS bars' volume", () => {
    // The invariant that catches a misaligned second aggregation: if the recent
    // slice were binned against its own min/max instead of the full window's,
    // the dots would land in shelves those bars never traded in — invisible
    // except by eye, but the total would still have to move.
    const expected = bars.slice(-RECENT_BARS).reduce((a, b) => a + b.volume, 0);
    const got = profile.bins.reduce((a, b) => a + b.recent, 0);
    expect(got).toBeCloseTo(expected, 3);
  });
});
