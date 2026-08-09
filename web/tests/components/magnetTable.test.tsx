import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import MagnetTable from "@/components/stock/tabs/technicals/MagnetTable";

const LEVELS = {
  resistance: 340.08,
  support: 275.15,
  stretch: 380.21,
  down: 235.02,
  sma20: 320,
  last: 313.33,
  leg_state: "falling",
  pivot_a: { index: 14, kind: "bottom", price: 275.15 },
  pivot_b: { index: 36, kind: "top", price: 340.08 },
};

describe("MagnetTable", () => {
  it("labels the 0.618 rows as having no measured edge", () => {
    render(<MagnetTable levels={LEVELS} />);
    expect(screen.getAllByText(/no measured edge/i).length).toBe(2);
  });

  it("never renders a distance-percent headline", () => {
    const { container } = render(<MagnetTable levels={LEVELS} />);
    expect(container.textContent).not.toMatch(/[+-]\d+\.\d%/);
  });

  it("renders all five rows in price order", () => {
    render(<MagnetTable levels={LEVELS} />);
    for (const label of ["STRETCH", "RESISTANCE", "LAST", "SUPPORT", "DOWN"])
      expect(screen.getByText(label)).toBeTruthy();
  });

  it("renders nothing when there is no confirmed swing", () => {
    const { container } = render(<MagnetTable levels={null} />);
    expect(container.textContent).toMatch(/no confirmed swing/i);
  });
});
