import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { CharmPanel } from "@/components/stock/panels/greeks/CharmPanel";

const strikeExposures = [
  {
    strike: "100",
    expiry: "2026-05-30",
    dte: 9,
    call_vanna: "0",
    put_vanna: "0",
    call_charm: "-2000",
    put_charm: "500",
  },
  {
    strike: "110",
    expiry: "2026-05-30",
    dte: 9,
    call_vanna: "0",
    put_vanna: "0",
    call_charm: "-3000",
    put_charm: "800",
  },
] as never[];

const summary = [
  {
    expiry: "2026-05-30",
    dte: 9,
    spot: "105",
    net_vanna: "0",
    top_vanna_strike: null,
    top_vanna_value: null,
    delta_shock_1pt_iv: null,
    vanna_regime: "neutral",
    vanna_flip: null,
    vanna_headline: "",
    vanna_subtitle: "",
    net_charm: "-3700",
    charm_pin_strike: "110",
    charm_above_sum: "-2200",
    charm_below_sum: "0",
    charm_imbalance_pct: "1.0",
    charm_signal_quality: "aligned",
    charm_flip: "108",
    charm_headline: "Mechanical SELL pressure into the close",
    charm_subtitle: "Strongest near $110.00",
  },
] as never[];

describe("CharmPanel", () => {
  it("renders the SELL pressure headline + 4 tiles + charts", () => {
    const { container, getByText } = render(
      <CharmPanel
        ticker="TSLA"
        strikeExposures={strikeExposures}
        summary={summary}
      />,
    );
    expect(getByText(/Mechanical SELL/)).toBeTruthy();
    expect(
      container.querySelectorAll("[data-testid='exposure-tile']"),
    ).toHaveLength(4);
    expect(
      container.querySelector("path[data-testid='net-line']"),
    ).not.toBeNull();
    expect(
      container.querySelector("path[data-testid='call-line']"),
    ).not.toBeNull();
    expect(
      container.querySelector("path[data-testid='put-line']"),
    ).not.toBeNull();
  });

  it("renders an empty state when no summary present", () => {
    const { queryByText } = render(
      <CharmPanel ticker="TSLA" strikeExposures={[]} summary={[]} />,
    );
    expect(queryByText(/not yet available/i)).not.toBeNull();
  });
});
