import { describe, expect, it } from "vitest";

import { curvatureField } from "@/components/shared/GexCurvatureChart";
import type { GexBucket } from "@/lib/regime/useGex";

function b(strike: number, net_gex: number): GexBucket {
  return {
    strike,
    call_gex: 0,
    put_gex: 0,
    net_gex,
    pct_from_spot: 0,
    tag: null,
  };
}

describe("curvatureField", () => {
  it("returns nulls at the endpoints and a signed second derivative inside", () => {
    // ∪-shaped (convex) → positive curvature at the interior point.
    const out = curvatureField([b(100, 10), b(105, -10), b(110, 10)]);
    expect(out[0]).toBeNull();
    expect(out[2]).toBeNull();
    expect(out[1]!).toBeGreaterThan(0);

    // ∩-shaped (concave) → negative.
    const down = curvatureField([b(100, -10), b(105, 10), b(110, -10)]);
    expect(down[1]!).toBeLessThan(0);
  });

  it("is flat on a straight line and handles uneven strike spacing", () => {
    const out = curvatureField([b(100, 0), b(103, 30), b(110, 100)]);
    expect(out[1]!).toBeCloseTo(0, 6);
  });

  it("returns all-null when there is no centred stencil", () => {
    expect(curvatureField([b(100, 1), b(105, 2)])).toEqual([null, null]);
  });
});
