/* @vitest-environment jsdom */
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import {
  GexProfileChart,
  buildStockGexProfile,
} from "@/components/stock/panels/GexProfileChart";

const curve = [
  // Same strike across two expiries — must aggregate.
  { strike: 105, net_gex: 1_000_000 },
  { strike: 105, net_gex: 500_000 },
  { strike: 95, net_gex: -12_500 },
  { strike: 100, net_gex: 4_000 },
  // Outside the ±15% window around spot=100.
  { strike: 200, net_gex: 9_000_000 },
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
] as any;

const levels = {
  gex_flip: { strike: 100 },
  call_wall: { strike: 105 },
  put_wall: { strike: 95 },
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
} as any;

const baseReport = {
  ticker: "AAPL",
  market_structure: { spot: 100 },
  market_structure_levels: levels,
  strike_gex_curve: curve,
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
} as any;

describe("buildStockGexProfile", () => {
  it("aggregates across expiries, clips to the window, and tags levels", () => {
    const out = buildStockGexProfile(curve, 100, levels);

    expect(out.map((b) => b.strike)).toEqual([95, 100, 105]);
    expect(out[2].net_gex).toBe(1_500_000);
    expect(out.map((b) => b.tag)).toEqual([
      "PUT WALL",
      "GEX FLIP",
      "CALL WALL",
    ]);
    expect(out[0].pct_from_spot).toBeCloseTo(-5, 6);
  });

  it("shrinks the window to the gamma-carrying span", () => {
    // Single-name shape: ~all the gamma sits within ±1% of spot, with a
    // near-zero tail out to ±10%. A fixed wide window would render the tail
    // as a dead flat line.
    const concentrated = [
      { strike: 90, net_gex: 50 },
      { strike: 99, net_gex: -800_000 },
      { strike: 100, net_gex: 200_000 },
      { strike: 101, net_gex: 900_000 },
      { strike: 110, net_gex: 50 },
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
    ] as any;

    const out = buildStockGexProfile(concentrated, 100, {});
    expect(out.map((b) => b.strike)).toEqual([99, 100, 101]);
  });

  it("keeps the full window when gamma is spread out", () => {
    // Index shape: mass is spread across the whole ±15% span, so the
    // coverage walk reaches the outermost strike and the clamp holds at max.
    const spread = Array.from({ length: 15 }, (_, i) => ({
      strike: 93 + i,
      net_gex: 100_000,
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
    })) as any;

    const out = buildStockGexProfile(spread, 100, {});
    expect(out).toHaveLength(15);
  });

  it("returns ascending strikes so the curvature stencil is valid", () => {
    const out = buildStockGexProfile(curve, 100, levels);
    for (let i = 1; i < out.length; i++) {
      expect(out[i].strike).toBeGreaterThan(out[i - 1].strike);
    }
  });
});

describe("GexProfileChart", () => {
  it("renders the curvature field with the spot and flip rules", () => {
    render(<GexProfileChart report={baseReport} />);

    expect(screen.getByText(/curvature field by strike/i)).not.toBeNull();
    expect(screen.getByText(/SPOT 100/)).not.toBeNull();
    expect(screen.getByText(/FLIP 100/)).not.toBeNull();
  });

  it("shows an anchor error when spot is missing", () => {
    render(
      <GexProfileChart
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        report={{ ...baseReport, market_structure: { spot: null } } as any}
      />,
    );
    expect(screen.getByText(/Spot unavailable/)).not.toBeNull();
  });
});
