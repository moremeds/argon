import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { RatesDesk } from "@/components/rates/RatesDesk";
import { SNAPSHOT, TENORS } from "./fixture";

describe("RatesDesk", () => {
  it("renders all reference-page anchors and KPI tiles", () => {
    render(<RatesDesk snapshot={SNAPSHOT} />);

    for (const label of [
      "Summary",
      "Curve",
      "Decomp",
      "Scorecard",
      "Policy",
      "Supply",
      "Positioning",
      "Cross-Market",
      "Events",
      "View",
    ]) {
      expect(screen.getByRole("link", { name: label })).toBeTruthy();
    }

    expect(screen.getByText("US Rates Factor Desk")).toBeTruthy();
    expect(screen.getByText("Treasury Factor Board")).toBeTruthy();
    expect(
      screen.getByText(/Snapshot update · .* HKT · FRED as of 2026-05-20/),
    ).toBeTruthy();

    for (const label of ["2Y", "5Y", "10Y", "30Y", "2s10s", "5s30s"]) {
      expect(screen.getAllByText(label).length).toBeGreaterThan(0);
    }
  });

  it("renders the full eleven-tenor curve table", () => {
    render(<RatesDesk snapshot={SNAPSHOT} />);

    const curveSection = screen.getByRole("region", {
      name: /yield curve/i,
    });
    for (const tenor of TENORS) {
      expect(
        within(curveSection).getByRole("row", {
          name: new RegExp(`^${tenor}\\b`),
        }),
      ).toBeTruthy();
    }
  });

  it("renders current, one-week, and one-month curve overlays from live deltas", () => {
    render(<RatesDesk snapshot={SNAPSHOT} />);

    expect(screen.getByText("PAR yield curve overlay")).toBeTruthy();
    expect(screen.getByText("Current")).toBeTruthy();
    expect(screen.getByText("1W ago")).toBeTruthy();
    expect(screen.getByText("1M ago")).toBeTruthy();
  });

  it("surfaces summary duration and curve stance from the scorecard", () => {
    render(<RatesDesk snapshot={SNAPSHOT} />);

    expect(screen.getByText("Duration stance")).toBeTruthy();
    expect(screen.getByText("Curve stance")).toBeTruthy();
    expect(
      screen.getAllByText("Neutral until the live FRED curve breaks range.")
        .length,
    ).toBeGreaterThan(1);
    expect(screen.getAllByText("Curve still biased flatter.").length)
      .toBeGreaterThan(1);
  });

  it("colors summary 1D bps changes by sign", () => {
    render(<RatesDesk snapshot={SNAPSHOT} />);

    expect(screen.getByText("-2.0 bps 1D").className).toContain(
      "deltaNegative",
    );
    expect(screen.getByText("+5.0 bps 1D").className).toContain(
      "deltaPositive",
    );
  });

  it("renders deterministic rule interpretations for slope cards", () => {
    render(<RatesDesk snapshot={SNAPSHOT} />);

    expect(screen.getByText("3m10y")).toBeTruthy();
    expect(
      screen.getByText(/easing or term premium pressure is visible/),
    ).toBeTruthy();
    expect(screen.getByText(/Belly is rich versus wings/)).toBeTruthy();
  });

  it("renders a live decomposition dashboard with attribution rows", () => {
    render(<RatesDesk snapshot={SNAPSHOT} />);

    expect(
      screen.getByText(
        "10Y nominal = E[short real] + E[short inflation] + real term premium + inflation risk premium",
      ),
    ).toBeTruthy();
    expect(screen.getByText(/Cleveland Fed model · 2026-05-01/)).toBeTruthy();
    expect(screen.getByText("Model nominal 10Y")).toBeTruthy();
    expect(screen.getByText("Expected short real")).toBeTruthy();
    expect(screen.getAllByText("Expected short inflation").length).toBeGreaterThan(1);
    expect(screen.getAllByText("Real term premium").length).toBeGreaterThan(1);
    expect(screen.getAllByText("Inflation risk premium").length).toBeGreaterThan(1);
    expect(screen.getAllByText("FRED residual").length).toBeGreaterThan(1);
    expect(screen.getByText("Live FRED 10Y")).toBeTruthy();
    expect(screen.getByText("Cleveland/FRED gap")).toBeTruthy();
    expect(screen.getByText(/not an extra Clarida component/)).toBeTruthy();
    expect(screen.getByText("Move attribution · bps")).toBeTruthy();
    expect(screen.getAllByText("+15.3").length).toBeGreaterThan(0);
    expect(screen.getAllByText("+19.7").length).toBeGreaterThan(0);
    expect(screen.getByText(/expected inflation contributes 5\.7 bps/)).toBeTruthy();
    expect(screen.getByText("Rates read")).toBeTruthy();
    expect(screen.getByText(/Cleveland's monthly model explains \+15\.3 bps/)).toBeTruthy();
    expect(screen.getByText(/daily FRED pricing has moved faster than the monthly Cleveland release/)).toBeTruthy();
  });

  it("marks not-yet-wired source panels unavailable instead of filling static values", () => {
    render(<RatesDesk snapshot={SNAPSHOT} />);

    expect(screen.getAllByText("Unavailable").length).toBeGreaterThan(0);
    expect(screen.getByText(/Treasury auction feed not wired/)).toBeTruthy();
    expect(screen.getByText(/CFTC\/TIC feeds not wired/)).toBeTruthy();
  });

  it("renders source freshness so failed refreshes do not look live", () => {
    render(<RatesDesk snapshot={SNAPSHOT} />);

    expect(screen.getByText("10Y Treasury")).toBeTruthy();
    expect(screen.getByText("Cleveland Fed 10Y expected inflation")).toBeTruthy();
    expect(screen.getByText("Stale")).toBeTruthy();
    expect(screen.getByText("FRED / Board of Governors")).toBeTruthy();
    expect(screen.getByText("Cleveland Fed Inflation Expectations")).toBeTruthy();
    expect(screen.getByRole("link", { name: "FRED DGS10" })).toHaveProperty(
      "href",
      "https://fred.stlouisfed.org/series/DGS10",
    );
    expect(
      screen.getByRole("link", { name: "Cleveland Fed CLEVE_EXPECTED_INFLATION_10Y" }),
    ).toHaveProperty(
      "href",
      "https://www.clevelandfed.org/indicators-and-data/inflation-expectations",
    );
  });

  it("renders an explicit empty state when no snapshot exists", () => {
    render(<RatesDesk snapshot={null} />);

    expect(screen.getByText(/Rates snapshot not computed/)).toBeTruthy();
  });
});
