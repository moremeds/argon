/* @vitest-environment jsdom */
import { describe, expect, it } from "vitest";

import { retagProfileForSpot } from "@/components/regime/GexSubTab";
import type { GexBucket } from "@/lib/regime/useGex";

function bucket(
  strike: number,
  tag: string | null = null,
  net_gex = 1000,
): GexBucket {
  return { strike, call_gex: 0, put_gex: 0, net_gex, pct_from_spot: 0, tag };
}

function level(strike: number) {
  return { strike, gamma: 1, distance: 0, distance_pct: 0 };
}

describe("retagProfileForSpot", () => {
  const profile = [
    bucket(7500, "MAX MAGNET"),
    bucket(7425, "GEX FLIP"),
    bucket(7400, "SPOT"),
    bucket(7375),
    bucket(7200, "MAX ACCELERATOR"),
  ];
  const levels = {
    gex_flip: level(7425),
    max_magnet: level(7500),
    second_magnet: null,
    max_accelerator: level(7200),
    put_wall: null,
    call_wall: null,
  };

  it("moves the SPOT tag to the strike nearest the live spot", () => {
    const out = retagProfileForSpot(profile, 7380, levels);
    expect(out.find((b) => b.tag === "SPOT")?.strike).toBe(7375);
    // The stale snapshot SPOT row is cleared.
    expect(out.find((b) => b.strike === 7400)?.tag).toBeNull();
  });

  it("keeps GEX FLIP precedence when spot sits on the flip strike", () => {
    const out = retagProfileForSpot(profile, 7424, levels);
    // Backend tag_profile: flip overwrites SPOT on the same strike.
    expect(out.find((b) => b.strike === 7425)?.tag).toBe("GEX FLIP");
    expect(out.some((b) => b.tag === "SPOT")).toBe(false);
  });

  it("recomputes pct_from_spot against the live spot", () => {
    const out = retagProfileForSpot(profile, 7400, levels);
    const b = out.find((x) => x.strike === 7500)!;
    expect(b.pct_from_spot).toBeCloseTo(((7500 - 7400) / 7400) * 100, 6);
  });

  it("re-surfaces a level tag suppressed by the snapshot SPOT placement", () => {
    // Snapshot had SPOT on 7400 suppressing nothing here, but if SPOT moves
    // off a level strike, the level label must come back.
    const withSpotOnLevel = [
      bucket(7500, "SPOT"), // snapshot spot sat on the magnet strike
      bucket(7425, "GEX FLIP"),
      bucket(7375),
    ];
    const out = retagProfileForSpot(withSpotOnLevel, 7376, levels);
    expect(out.find((b) => b.strike === 7500)?.tag).toBe("MAX MAGNET");
    expect(out.find((b) => b.strike === 7375)?.tag).toBe("SPOT");
  });

  it("returns the input untouched when the profile is empty", () => {
    expect(retagProfileForSpot([], 7400, levels)).toEqual([]);
  });
});
