/* @vitest-environment jsdom */
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { HistoryChart } from "@/components/regime/HistoryChart";
import type { GexHistoryEntry } from "@/lib/regime/useGex";

const sample: GexHistoryEntry[] = [
  {
    date: "2026-05-01",
    net_gex: 1e9,
    net_dex: 1e8,
    gex_flip: 7395,
    spot: 7400,
    atm_iv: null,
    vol_pc: null,
    bias: null,
  },
  {
    date: "2026-05-02",
    net_gex: 1.1e9,
    net_dex: 1.1e8,
    gex_flip: 7398,
    spot: 7430,
    atm_iv: null,
    vol_pc: null,
    bias: null,
  },
  {
    date: "2026-05-03",
    net_gex: 0.9e9,
    net_dex: 0.9e8,
    gex_flip: 7402,
    spot: 7408,
    atm_iv: null,
    vol_pc: null,
    bias: null,
  },
];

describe("HistoryChart", () => {
  it("renders an SVG with the right title", () => {
    render(<HistoryChart history={sample} ticker="SPX" />);
    expect(screen.getByRole("img", { name: /history/i })).toBeTruthy();
  });

  it("renders empty state for no history", () => {
    render(<HistoryChart history={[]} ticker="SPX" />);
    expect(screen.getByText(/no history/i)).toBeTruthy();
  });

  it("plots net_gex and gex_flip paths", () => {
    const { container } = render(
      <HistoryChart history={sample} ticker="SPX" />,
    );
    const paths = container.querySelectorAll("path");
    expect(paths.length).toBeGreaterThanOrEqual(2);
  });
});
