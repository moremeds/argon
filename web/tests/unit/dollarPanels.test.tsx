import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import {
  UsdDollarSection,
  type Dxy,
} from "@/components/macro/goldFactor/DollarPanels";

import { GOLD_FACTOR } from "../fixtures/goldFactor";

// Labelled synthetic index (not market data): last year's close, then 30 rows this year,
// every row moved by +0.1 on EURUSD's part only, so each window's parts sum is 0.1 × rows.
const DXY: Dxy = {
  computed_at: "2026-10-13T21:40:00Z",
  last_date: "2026-02-11",
  points: [
    { obs_date: "2025-12-31", dxy: 100, change_pct: null, eurusd_part: null, usdjpy_part: null,
      gbpusd_part: null, usdcad_part: null, usdsek_part: null, usdchf_part: null },
    ...Array.from({ length: 30 }, (_, i) => ({
      obs_date: `2026-0${1 + Math.floor(i / 20)}-${String((i % 20) + 1).padStart(2, "0")}`,
      dxy: 100 * Math.exp((0.1 * (i + 1)) / 100),
      change_pct: 0.1, eurusd_part: 0.1, usdjpy_part: 0, gbpusd_part: 0,
      usdcad_part: 0, usdsek_part: 0, usdchf_part: 0,
    })),
  ],
}; // prettier-ignore

describe("UsdDollarSection", () => {
  it("splits each window's move by currency and the parts add up", () => {
    render(
      <UsdDollarSection dxy={{ value: DXY }} factor={{ value: GOLD_FACTOR }} />,
    );
    const cap = () => screen.getByTestId("usd-dxy-parts-cap").textContent;
    expect(cap()).toMatch(/currencies sum to \+2\.10/); // month: 21 rows
    const parts = screen.getByRole("group", { name: "Window" });
    fireEvent.click(within(parts).getByText("1W"));
    expect(cap()).toMatch(/currencies sum to \+0\.50/);
    fireEvent.click(within(parts).getByText("YTD"));
    expect(cap()).toMatch(/2025-12-31 → .*currencies sum to \+3\.00/);
  });

  it("shows gold's dollar slope with its interval and the month split", () => {
    render(
      <UsdDollarSection dxy={{ value: DXY }} factor={{ value: GOLD_FACTOR }} />,
    );
    expect(screen.getByText("Gold's sensitivity to the dollar")).toBeTruthy();
    expect(screen.getByText(/95% interval −3\.40 to −1\.30/)).toBeTruthy();
    expect(screen.getByText("This month: gold and its dollar part")).toBeTruthy();
  });

  it("says the index is not computed yet rather than drawing an empty panel", () => {
    render(<UsdDollarSection dxy={{ value: null }} factor={{ value: null }} />);
    expect(screen.getByText(/Dollar index not computed yet/)).toBeTruthy();
    expect(screen.queryByText("Gold's sensitivity to the dollar")).toBeNull();
  });
});
