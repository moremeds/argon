/* @vitest-environment jsdom */
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { MagnetGammaBar } from "@/components/stock/panels/MagnetGammaBar";

const baseReport = {
  ticker: "TSLA",
  market_structure: { spot: 410, net_gex: 216910 },
  market_structure_levels: {
    call_wall: { strike: 450, net_gex: 46550 },
    put_wall: { strike: 395, net_gex: -966840 },
    gex_flip: { strike: 474.64, net_gex: 0 },
  },
  dealer_regime: {
    label: "dampening",
    headline: "Long Γ → Dampening regime",
    subtitle:
      "Largest level is the call wall (resistance) at $450.00 — dealers may sell into rallies as price approaches it.",
    prev_close_net_gex: 440500,
    odte_net_gex: -20133,
  },
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
} as any;

describe("MagnetGammaBar", () => {
  it("renders the regime headline and subtitle", () => {
    render(<MagnetGammaBar report={baseReport} />);
    expect(screen.getByTestId("magnet-gamma-headline").textContent).toBe(
      "Long Γ → Dampening regime",
    );
    expect(screen.getByTestId("magnet-gamma-subtitle").textContent).toContain(
      "Largest level is the call wall",
    );
  });

  it("shows the five metric tile labels", () => {
    render(<MagnetGammaBar report={baseReport} />);
    expect(screen.getByText("Net dealer Γ")).not.toBeNull();
    expect(screen.getByText("Γ vs prev close")).not.toBeNull();
    expect(screen.getByText("Top wall")).not.toBeNull();
    expect(screen.getByText("Flip distance")).not.toBeNull();
    expect(screen.getByText("0–1d rolls off")).not.toBeNull();
  });

  it("formats flip distance from spot", () => {
    render(<MagnetGammaBar report={baseReport} />);
    // (474.64 - 410) / 410 = 0.1576 → "+15.8%"
    expect(screen.getByTestId("magnet-gamma-flip-dist").textContent).toContain(
      "+15.8%",
    );
  });

  it("formats compact signed money values with fixed two-decimal suffixes", () => {
    const { container } = render(<MagnetGammaBar report={baseReport} />);
    expect(container.textContent).toContain("+$216.91K");
    expect(container.textContent).toContain("-$223.59K");
    expect(container.textContent).toContain("-$966.84K");
    expect(container.textContent).toContain("-$20.13K");
  });

  it("renders nothing when dealer_regime missing", () => {
    const empty = { ...baseReport, dealer_regime: null };
    const { container } = render(<MagnetGammaBar report={empty} />);
    expect(container.firstChild).toBeNull();
  });
});
