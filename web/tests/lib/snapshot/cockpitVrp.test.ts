// cockpitVrp had NO prior tests — the oracle below is the pre-move inline
// expression from CockpitVrpTab.tsx (points[].vrp → toNum → population sd →
// mean ± 0.5·sd band → per-row z), pinned against the frozen SPY payload.
import { describe, expect, it } from "vitest";
import type { CockpitVrpResponse } from "@/lib/api";
import { toNum } from "@/lib/formatters";
import { meanStd, vrpBand, vrpStats, vrpZ } from "@/lib/snapshot/cockpitVrp";
import spy from "@/tests/fixtures/mcp/spy_cockpit_vrp.json";

const VRP = spy as unknown as CockpitVrpResponse;
const points = VRP.points!;

// Pre-move oracle: verbatim from CockpitVrpTab.
function oracleStats(pts: typeof points) {
  const vrpValues = pts
    .map((point) => toNum(point.vrp))
    .filter((value): value is number => value != null);
  const n = vrpValues.length;
  const mean = n ? vrpValues.reduce((s, v) => s + v, 0) / n : 0;
  const variance = n
    ? vrpValues.reduce((s, v) => s + (v - mean) ** 2, 0) / n
    : 0;
  const std = Math.sqrt(variance);
  return { vrpValues, stats: { mean, std } };
}

describe("meanStd (population sd)", () => {
  it("returns zero stats on empty input", () => {
    expect(meanStd([])).toEqual({ mean: 0, std: 0 });
  });

  it("is a population sd: divides by n, not n-1", () => {
    const { mean, std } = meanStd([1, 2, 3, 4]);
    expect(mean).toBe(2.5);
    expect(std).toBe(Math.sqrt(1.25)); // population variance 1.25, not sample 1.6667
  });

  it("matches the oracle on the frozen SPY payload", () => {
    const oracle = oracleStats(points);
    expect(vrpStats(points)).toEqual(oracle.stats);
    expect(vrpStats(points).mean).toBeCloseTo(0.009599874810176883, 15);
    expect(vrpStats(points).std).toBeCloseTo(0.02854882721294914, 15);
  });
});

describe("vrpBand", () => {
  it("is mean ± 0.5·sd", () => {
    const band = vrpBand(vrpStats(points));
    expect(band).toBeDefined();
    expect(band!.min).toBeCloseTo(-0.004674538796297686, 15);
    expect(band!.max).toBeCloseTo(0.023874288416651453, 15);
    const stats = vrpStats(points);
    expect(band!.min).toBe(stats.mean - 0.5 * stats.std);
    expect(band!.max).toBe(stats.mean + 0.5 * stats.std);
  });

  it("returns undefined when sd = 0", () => {
    expect(vrpBand({ mean: 5, std: 0 })).toBeUndefined();
    expect(vrpBand(meanStd([7, 7, 7]))).toBeUndefined();
  });
});

describe("vrpZ", () => {
  it("is (vrp - mean) / sd over real fixture values", () => {
    const stats = vrpStats(points);
    const first = points.find((p) => toNum(p.vrp) != null)!;
    const z = vrpZ(toNum(first.vrp), stats);
    expect(z).toBe((toNum(first.vrp)! - stats.mean) / stats.std);
    expect(z).toBeCloseTo(-0.2676, 3);
  });

  it("is null when vrp is missing or sd = 0", () => {
    const stats = vrpStats(points);
    const latest = points[points.length - 1]; // fixture's latest has vrp null
    expect(toNum(latest.vrp)).toBeNull();
    expect(vrpZ(toNum(latest.vrp), stats)).toBeNull();
    expect(vrpZ(0.01, { mean: 0.01, std: 0 })).toBeNull();
    expect(vrpZ(null, stats)).toBeNull();
  });
});
