// cockpitDealer had NO prior tests — oracles are the pre-move expressions from
// CockpitDealerTab.tsx (groupByExpiry / totals / peaks / maxAbs / netValue),
// pinned against the frozen SPY dealer payload plus literal branch cases.
import { describe, expect, it } from "vitest";
import type { CockpitDealerResponse } from "@/lib/api";
import { toNum } from "@/lib/formatters";
import {
  groupByExpiry,
  maxAbs,
  netValue,
  peaks,
  totals,
  type DealerPoint,
} from "@/lib/snapshot/cockpitDealer";
import spy from "@/tests/fixtures/mcp/spy_cockpit_dealer.json";

const DEALER = spy as unknown as CockpitDealerResponse;
const points = DEALER.points!;

const row = (over: Partial<DealerPoint>): DealerPoint => ({
  expiry: "2099-01-01",
  strike: "100",
  ...over,
});

describe("groupByExpiry", () => {
  it("groups by stringified expiry, sorts expiries lexically and strikes numerically", () => {
    const pts = [
      row({ expiry: "2026-10-01", strike: "110" }),
      row({ expiry: "2026-09-01", strike: "90" }),
      row({ expiry: "2026-09-01", strike: "105" }),
      row({ expiry: "2026-09-01", strike: "95" }),
    ];
    const groups = groupByExpiry(pts);
    expect(groups.map(([e]) => e)).toEqual(["2026-09-01", "2026-10-01"]);
    expect(groups[0][1].map((r) => toNum(r.strike))).toEqual([90, 95, 105]);
  });

  it("matches the oracle on the frozen SPY payload (single 171-point expiry)", () => {
    const groups = groupByExpiry(points).slice(0, 6);
    expect(groups).toHaveLength(1);
    expect(groups[0][0]).toBe("2026-09-23");
    expect(groups[0][1]).toHaveLength(171);
    const strikes = groups[0][1].map((r) => toNum(r.strike)!);
    for (let i = 1; i < strikes.length; i++)
      expect(strikes[i]).toBeGreaterThanOrEqual(strikes[i - 1]);
  });
});

describe("netValue", () => {
  it("prefers exposure_* when either side is present", () => {
    const p = row({
      exposure_call_vanna: "1.5",
      exposure_put_vanna: null,
      call_vanna: "999",
      put_vanna: "999",
    });
    expect(netValue(p, "vanna")).toBe(1.5); // exposure wins; missing side coerces to 0
  });

  it("falls back to raw call_/put_ when both exposures are absent", () => {
    const p = row({ call_charm: "2", put_charm: "3" });
    expect(netValue(p, "charm")).toBe(5);
    expect(netValue(row({ call_charm: "2" }), "charm")).toBe(2);
  });

  it("is null when both raw values are missing", () => {
    expect(netValue(row({}), "vanna")).toBeNull();
  });

  it("matches the raw-vs-exposure oracle on every fixture point", () => {
    for (const p of points) {
      const ce = toNum(p.exposure_call_vanna);
      const pe = toNum(p.exposure_put_vanna);
      const oracle =
        ce != null || pe != null
          ? (ce ?? 0) + (pe ?? 0)
          : toNum(p.call_vanna) == null && toNum(p.put_vanna) == null
            ? null
            : (toNum(p.call_vanna) ?? 0) + (toNum(p.put_vanna) ?? 0);
      expect(netValue(p, "vanna")).toBe(oracle);
    }
  });
});

describe("totals / peaks / maxAbs", () => {
  const primary = groupByExpiry(points).slice(0, 6)[0]?.[1] ?? [];

  it("sums nets across the frozen primary expiry", () => {
    const t = totals(primary);
    expect(t.vanna).toBeCloseTo(2438816.878300002, 6);
    expect(t.charm).toBeCloseTo(-8524234.137999915, 6);
    const oracle = primary.reduce(
      (acc, p) => ({
        vanna: acc.vanna + (netValue(p, "vanna") ?? 0),
        charm: acc.charm + (netValue(p, "charm") ?? 0),
      }),
      { vanna: 0, charm: 0 },
    );
    expect(t).toEqual(oracle);
  });

  it("returns both peak strikes (780/780 on the frozen payload)", () => {
    expect(peaks(primary)).toEqual({ vannaStrike: 780, charmStrike: 780 });
  });

  it("empty input: totals zero, peaks null, maxAbs null", () => {
    expect(totals([])).toEqual({ vanna: 0, charm: 0 });
    expect(peaks([])).toEqual({ vannaStrike: null, charmStrike: null });
    expect(maxAbs([], "vanna")).toBeNull();
  });

  it("ties keep the FIRST row in order (strict > comparison)", () => {
    const tied = [
      row({ strike: "100", exposure_call_vanna: "5" }),
      row({ strike: "200", exposure_call_vanna: "-5" }),
    ];
    expect(maxAbs(tied, "vanna")?.strike).toBe("100");
    // All-null nets never beat the -1 sentinel → maxAbs returns null.
    const allNull = [row({ strike: "300" }), row({ strike: "301" })];
    expect(maxAbs(allNull, "vanna")).toBeNull();
  });
});
