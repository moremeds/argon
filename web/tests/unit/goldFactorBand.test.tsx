import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { GoldFactorBand } from "@/components/gold/factor/GoldFactorBand";
import type { components } from "@/lib/types";

type Factor = components["schemas"]["GoldFactorResponse"];

// Labelled synthetic model output (not market data): 30 rows whose parts add up exactly.
const points = Array.from({ length: 30 }, (_, i) => ({
  obs_date: `2026-09-${String(i + 1).padStart(2, "0")}`,
  b_r: -0.05, b_r_lo95: -0.12, b_r_hi95: 0.01,
  b_d: -2.3, b_d_lo95: -3.4, b_d_hi95: -1.3,
  b_s: 0.7, b_s_lo95: -0.4, b_s_hi95: 1.7,
  explained_share: 0.26,
  published_label: "part" as const,
  real_yield_part: -0.1, dollar_part: 0.2, haven_part: 0.05,
  own_trailing_drift: 0.1, unexplained_1: 0.25,
  gold_change: 0.5,
  unexplained_21: null,
}));
const FIXTURE: Factor = {
  computed_at: "2026-10-10T21:40:00Z",
  last_date: "2026-09-30",
  explained_low: 0.218,
  explained_high: 0.402,
  points,
  years: [
    { year: 2025, rows: 250, partial_year: false, gold_change: 40, own_trailing_drift: 20,
      real_yield_part: 5, dollar_part: 8, haven_part: 1, unexplained: 6, explained_share: 0.3 },
    { year: 2026, rows: 30, partial_year: true, gold_change: 15, own_trailing_drift: 3,
      real_yield_part: -3, dollar_part: 6, haven_part: 1.5, unexplained: 7.5, explained_share: 0.2 },
  ],
}; // prettier-ignore

describe("GoldFactorBand", () => {
  it("renders the six panels, each labelled as historical description", () => {
    render(<GoldFactorBand data={FIXTURE} />);
    const band = screen.getByTestId("gold-factor-band");
    for (const id of ["sensitivity", "explained", "breakdown", "ytd", "yearly", "slope-history"]) {
      expect(band.querySelector(`#gold-factor-${id}`)).not.toBeNull();
    }
    expect(within(band).getAllByText(/Historical description, not a forecast/).length).toBeGreaterThanOrEqual(6);
    expect(within(band).getByText(/explain part/)).toBeTruthy();
  });

  it("waterfall sums the window and ends at gold's own change", () => {
    render(<GoldFactorBand data={FIXTURE} />);
    const panel = document.getElementById("gold-factor-breakdown")!;
    // 21 rows x 0.5 = +10.5 on the default window; 5 rows x 0.5 = +2.5 after the toggle
    expect(within(panel).getByText("+10.5")).toBeTruthy();
    fireEvent.click(within(panel).getByRole("button", { name: "5 days" }));
    expect(within(panel).getByText("+2.5")).toBeTruthy();
  });
});
