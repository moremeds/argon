/* @vitest-environment jsdom */
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { VolatilityRegimePanel } from "@/components/stock/panels/VolatilityRegimePanel";

const fixture = {
  status: "ok",
  ticker: "TSLA",
  scan_time: "",
  spot: 410,
  net_gex: 216910,
  prev_close_net_gex: 440500,
  signal: {
    label: "dampening",
    score: 0.62,
    gamma_score: 0.7,
    vanna_score: 0.18,
    charm_score: -0.12,
    headline: "Long Γ → Dampening regime",
    subtitle: "Largest level …",
  },
  closest_levels: [
    {
      label: "Accel ↑",
      direction: "up",
      role: "accelerator",
      strike: 410,
      distance_pct: 0,
      gamma: 19210,
      rank_kind: "nearest",
    },
    {
      label: "Put Wall",
      direction: "down",
      role: "support",
      strike: 395,
      distance_pct: -0.037,
      gamma: -966840,
      rank_kind: "nearest",
    },
    {
      label: "Call Wall",
      direction: "up",
      role: "resistance",
      strike: 450,
      distance_pct: 0.098,
      gamma: 46550,
      rank_kind: "nearest",
    },
    // A 'dominant' duplicate the panel should NOT render in the nearest section.
    {
      label: "Put Wall",
      direction: "down",
      role: "support",
      strike: 395,
      distance_pct: -0.037,
      gamma: -966840,
      rank_kind: "dominant",
    },
  ],
  odte_gex: -20132.93,
  odte_share_pct: 0.07,
  gamma_decay: [
    {
      dte: 0,
      expiry: "2026-05-18",
      net_gex: -20133,
      share_pct: 0.21,
      gross_abs_gex: 20133,
      gross_share_pct: 0.21,
    },
    {
      dte: 2,
      expiry: "2026-05-20",
      net_gex: -8511,
      share_pct: 0.09,
      gross_abs_gex: 8511,
      gross_share_pct: 0.09,
    },
    {
      dte: 4,
      expiry: "2026-05-22",
      net_gex: 41550,
      share_pct: 0.43,
      gross_abs_gex: 41550,
      gross_share_pct: 0.43,
    },
    {
      dte: 8,
      expiry: "2026-05-26",
      net_gex: 5031,
      share_pct: 0.05,
      gross_abs_gex: 5031,
      gross_share_pct: 0.05,
    },
  ],
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
} as any;

describe("VolatilityRegimePanel", () => {
  it("renders empty placeholder when data is null", () => {
    const { container } = render(<VolatilityRegimePanel data={null} />);
    expect(container.textContent).toContain("No dealer regime data yet.");
  });

  it("shows Dampening label", () => {
    render(<VolatilityRegimePanel data={fixture} />);
    expect(screen.getByTestId("regime-label").textContent).toBe("dampening");
  });

  it("renders Γ / V / C scores", () => {
    render(<VolatilityRegimePanel data={fixture} />);
    expect(screen.getByText("+0.70")).not.toBeNull();
    expect(screen.getByText("+0.18")).not.toBeNull();
    expect(screen.getByText("-0.12")).not.toBeNull();
  });

  it("lists nearest closest levels only (skips 'dominant' duplicates)", () => {
    render(<VolatilityRegimePanel data={fixture} />);
    const rows = screen.getAllByTestId("closest-level-row");
    expect(rows.length).toBe(3);
    expect(rows[0].textContent).toContain("Accel");
    expect(rows[1].textContent).toContain("Put Wall");
    expect(rows[2].textContent).toContain("Call Wall");
  });

  it("renders 0DTE GEX with chain share", () => {
    render(<VolatilityRegimePanel data={fixture} />);
    const odte = screen.getByTestId("odte-gex");
    expect(odte.textContent).toContain("-$20.13K");
    expect(odte.textContent).toContain("7% of chain");
  });

  it("renders one row per gamma decay bucket", () => {
    render(<VolatilityRegimePanel data={fixture} />);
    expect(screen.getAllByTestId("decay-row").length).toBe(4);
  });
});
