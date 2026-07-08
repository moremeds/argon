/* @vitest-environment jsdom */
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ForwardReturnTable } from "@/components/stock/panels/ForwardReturnTable";
import { TechnicalsKpiStrip } from "@/components/stock/panels/TechnicalsKpiStrip";

const base = {
  ticker: "NVDA",
  backfill_status: "ready",
  as_of: "2026-07-07",
  bars_n: 500,
  header: {
    price: 100.5,
    sma200: 95.0,
    dist_pct: 0.0579,
    z: 1.2,
    z_band: "STRETCHED HIGH",
    slope_ann: 0.12,
    slope_regime: "STRONG UPTREND",
    composite: 0.4,
  },
  series: [],
  detail: null,
  macd_watchlist_pctile: 0.8,
  forward_returns: [
    {
      band: "STRETCHED HIGH",
      horizon: 40,
      count: 33,
      mean: 0.015,
      median: 0.01,
      win_rate: 0.61,
    },
    {
      band: "NEUTRAL",
      horizon: 40,
      count: 120,
      mean: 0.008,
      median: 0.007,
      win_rate: 0.55,
    },
  ],
} as never;

describe("TechnicalsKpiStrip", () => {
  it("renders band + regime labels without NaN", () => {
    const { container } = render(<TechnicalsKpiStrip data={base} />);
    expect(screen.getByText("STRETCHED HIGH")).toBeDefined();
    expect(screen.getByText("STRONG UPTREND")).toBeDefined();
    expect(container.textContent).not.toContain("NaN");
  });

  it("null header fields render as dashes, not NaN", () => {
    const empty = {
      ...base,
      header: { ...base.header, z: null, composite: null },
    } as never;
    const { container } = render(<TechnicalsKpiStrip data={empty} />);
    expect(container.textContent).not.toContain("NaN");
  });
});

describe("ForwardReturnTable", () => {
  it("highlights the current band row and renders counts", () => {
    const { container } = render(<ForwardReturnTable data={base} />);
    expect(screen.getByText("STRETCHED HIGH")).toBeDefined();
    expect(screen.getByText("33")).toBeDefined();
    expect(container.textContent).not.toContain("NaN");
  });
});
