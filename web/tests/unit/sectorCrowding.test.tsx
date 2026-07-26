import { render, screen, fireEvent } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { SectorCrowdingPanel } from "@/components/regime/SectorCrowdingPanel";
import type { SectorCrowdingData } from "@/lib/regime/useSectorCrowding";

// Frozen from a live UW probe on 2026-07-24 plus warm-store iv_rank
// on 2026-07-25. See docs/research/2026-07-26-sector-crowding-probe.md.
const DATA: SectorCrowdingData = {
  as_of: "2026-07-24",
  benchmark: "SPY",
  rows: [
    {
      ticker: "SOXX",
      price: { name: "price", raw: 53.69, score: 97.0, band: "CROWDED" },
      flow: { name: "flow", raw: 26.47, score: 100.0, band: "CROWDED" },
      premium: { name: "premium", raw: 64.23, score: 100.0, band: "CROWDED" },
      score: 98.33,
      state: "CROWDED",
      binding_leg: "price",
      series: [
        {
          obs_date: "2026-07-23",
          etf_cum_return: 0,
          bench_cum_return: 0,
          flow_aum_pct: 20.1,
        },
        {
          obs_date: "2026-07-24",
          etf_cum_return: 25.59,
          bench_cum_return: 4.98,
          flow_aum_pct: 26.47,
        },
      ],
    },
    {
      ticker: "SMH",
      price: { name: "price", raw: 17.88, score: 46.0, band: "NORMAL" },
      flow: { name: "flow", raw: 1.91, score: 39.1, band: "NORMAL" },
      premium: { name: "premium", raw: 63.48, score: 100.0, band: "CROWDED" },
      score: 61.7,
      state: "NORMAL",
      // Weakest band is NORMAL (price 46.0 and flow 39.1 both sit there);
      // flow is the lower of the two, so it is the binding leg.
      binding_leg: "flow",
      series: [
        {
          obs_date: "2026-07-23",
          etf_cum_return: 0,
          bench_cum_return: 0,
          flow_aum_pct: 3.1,
        },
        {
          obs_date: "2026-07-24",
          etf_cum_return: 17.88,
          bench_cum_return: 4.98,
          flow_aum_pct: 1.91,
        },
      ],
    },
  ],
};

describe("SectorCrowdingPanel", () => {
  it("renders a row per ETF with its state", () => {
    render(<SectorCrowdingPanel data={DATA} />);
    expect(screen.getByTestId("sector-crowding-row-SOXX")).toBeTruthy();
    expect(screen.getByTestId("sector-crowding-row-SMH")).toBeTruthy();
    expect(
      screen.getByTestId("sector-crowding-state-SOXX").textContent,
    ).toContain("CROWDED");
  });

  it("names the binding leg so a demotion is explainable", () => {
    render(<SectorCrowdingPanel data={DATA} />);
    // SMH's premium leg is pinned at 100, but price (46th) and flow (39th)
    // are both only NORMAL -- the min-band rule demotes the row, and the UI
    // must name flow, the weaker of the two, as the constraint.
    const state = screen.getByTestId("sector-crowding-state-SMH");
    expect(state.textContent).toContain("NORMAL");
    expect(state.textContent).toContain("flow");
  });

  it("shows the raw value alongside its percentile", () => {
    render(<SectorCrowdingPanel data={DATA} />);
    const cell = screen.getByTestId("sector-crowding-price-SOXX");
    expect(cell.textContent).toContain("53.7");
    expect(cell.textContent).toContain("97");
  });

  it("expands the drill-down charts on row click", () => {
    render(<SectorCrowdingPanel data={DATA} />);
    expect(screen.queryByTestId("sector-crowding-charts")).toBeNull();
    fireEvent.click(screen.getByTestId("sector-crowding-row-SOXX"));
    expect(screen.getByTestId("sector-crowding-charts")).toBeTruthy();
  });

  it("renders an empty state when there are no rows", () => {
    render(
      <SectorCrowdingPanel
        data={{ as_of: null, benchmark: "SPY", rows: [] }}
      />,
    );
    expect(screen.getByTestId("sector-crowding-empty")).toBeTruthy();
  });
});
