import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { TechnicalsResponse } from "@/lib/api";
import { ForwardReturnTable } from "@/components/stock/panels/ForwardReturnTable";

const data = {
  bars_n: 1300,
  header: { z_band: "MILD LOW" },
  forward_returns: [
    {
      band: "OVERSOLD",
      horizon: 20,
      count: 73,
      mean: 0.025,
      median: -0.001,
      win_rate: 0.49,
    },
    {
      band: "OVERSOLD",
      horizon: 40,
      count: 73,
      mean: 0.057,
      median: 0.051,
      win_rate: 0.67,
    },
    {
      band: "OVERSOLD",
      horizon: 60,
      count: 73,
      mean: 0.076,
      median: 0.033,
      win_rate: 0.73,
    },
  ],
} as unknown as TechnicalsResponse;

describe("ForwardReturnTable", () => {
  it("defaults to the all-horizons (20/40/60d) view", () => {
    const { getByText, getByRole } = render(<ForwardReturnTable data={data} />);
    expect(getByText("20 / 40 / 60d")).toBeTruthy();
    // default is all-horizons, so the toggle offers to collapse to 40d only
    expect(getByRole("button", { name: /40d only/i })).toBeTruthy();
  });

  it("renders per-column aligned sub-headers over each horizon group", () => {
    const { getAllByText } = render(<ForwardReturnTable data={data} />);
    // Scope to <th> so the how-to-read prose ("N = how many…", "Win% = …")
    // isn't miscounted as a column header.
    expect(getAllByText("N", { selector: "th" }).length).toBe(3);
    expect(getAllByText(/^Win%$/i, { selector: "th" }).length).toBe(3);
  });

  it("explains how to read the table", () => {
    const { getByText } = render(<ForwardReturnTable data={data} />);
    expect(getByText(/How to read:/i)).toBeTruthy();
  });
});
