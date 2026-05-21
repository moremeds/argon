import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { VannaPanel } from "@/components/stock/panels/greeks/VannaPanel";

const strikeExposures = [
  {
    strike: "100",
    expiry: "2026-05-30",
    dte: 9,
    call_vanna: "100",
    put_vanna: "-30",
    call_charm: "0",
    put_charm: "0",
  },
  {
    strike: "110",
    expiry: "2026-05-30",
    dte: 9,
    call_vanna: "200",
    put_vanna: "-80",
    call_charm: "0",
    put_charm: "0",
  },
] as never[];

const summary = [
  {
    expiry: "2026-05-30",
    dte: 9,
    spot: "105",
    net_vanna: "190",
    top_vanna_strike: "110",
    top_vanna_value: "120",
    delta_shock_1pt_iv: "1.9",
    vanna_regime: "procyclical",
    vanna_flip: "108",
    vanna_headline:
      "Long Vanna — IV spikes pressure stock lower via dealer selling",
    vanna_subtitle: "subtitle...",
    net_charm: "0",
    charm_pin_strike: null,
    charm_above_sum: "0",
    charm_below_sum: "0",
    charm_imbalance_pct: null,
    charm_signal_quality: "weak",
    charm_flip: null,
    charm_headline: "",
    charm_subtitle: "",
  },
] as never[];

describe("VannaPanel", () => {
  it("renders headline, four tiles, expiry dropdown, and both charts", () => {
    const { container, getByText } = render(
      <VannaPanel
        ticker="TSLA"
        strikeExposures={strikeExposures}
        summary={summary}
      />,
    );
    expect(getByText(/Long Vanna/)).toBeTruthy();
    expect(
      container.querySelectorAll("[data-testid='exposure-tile']"),
    ).toHaveLength(4);
    expect(container.querySelector("select")).not.toBeNull();
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

  it("renders an empty state when there's no summary at all", () => {
    const { queryByText } = render(
      <VannaPanel ticker="TSLA" strikeExposures={[]} summary={[]} />,
    );
    expect(queryByText(/not yet available/i)).not.toBeNull();
  });
});
