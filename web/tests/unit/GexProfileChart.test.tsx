/* @vitest-environment jsdom */
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { GexProfileChart } from "@/components/stock/panels/GexProfileChart";

const baseReport = {
  market_structure: { spot: 100 },
  market_structure_levels: {},
  strike_gex_curve: [
    { strike: 110, net_gex: 1_500_000 },
    { strike: 90, net_gex: -12_500 },
  ],
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
} as any;

describe("GexProfileChart", () => {
  it("formats signed distance percentages and compact signed money labels", () => {
    render(<GexProfileChart report={baseReport} />);

    expect(screen.getByText("+10.00%")).not.toBeNull();
    expect(screen.getByText("-10.00%")).not.toBeNull();
    expect(screen.getByText("+$1.5M")).not.toBeNull();
    expect(screen.getByText("-$12.5K")).not.toBeNull();
  });
});
