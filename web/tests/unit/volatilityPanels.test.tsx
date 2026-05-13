/* @vitest-environment jsdom */
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { AnalyticalSeriesPanel } from "@/components/stock/panels/AnalyticalSeriesPanel";
import { DivergenceOverlay } from "@/components/stock/panels/DivergenceOverlay";
import { HvIvChart } from "@/components/stock/panels/HvIvChart";
import { IvOfIvChart } from "@/components/stock/panels/IvOfIvChart";
import { IvPercentileDistribution } from "@/components/stock/panels/IvPercentileDistribution";
import { RegimeQuadrantChart } from "@/components/stock/panels/RegimeQuadrantChart";
import { RvSpyCorrChart } from "@/components/stock/panels/RvSpyCorrChart";
import { SmileChart } from "@/components/stock/panels/SmileChart";
import { TermStructureChart } from "@/components/stock/panels/TermStructureChart";
import { VolMetricsCard } from "@/components/stock/panels/VolMetricsCard";
import { VrpSpreadPanel } from "@/components/stock/panels/VrpSpreadPanel";

describe("AnalyticalSeriesPanel", () => {
  it("renders header, subtitle, and headline", () => {
    render(
      <AnalyticalSeriesPanel
        title="IV / IV-of-IV"
        subtitle="Analytical time series"
        headline="+0.83σ"
      >
        <svg data-testid="chart" />
      </AnalyticalSeriesPanel>,
    );
    expect(screen.getByText("IV / IV-of-IV")).toBeDefined();
    expect(screen.getByText("Analytical time series")).toBeDefined();
    expect(screen.getByText("+0.83σ")).toBeDefined();
    expect(screen.getByTestId("chart")).toBeDefined();
  });
});

describe("VolMetricsCard", () => {
  it("renders the VRP badge and note", () => {
    render(
      <VolMetricsCard
        header={{
          iv: "0.53",
          rv: "0.41",
          iv_rank: "21",
          iv_percentile_30d: "52",
          implied_move_30d_perc: "0.046",
          skew_25d: "-0.0079",
          vrp: "0.42",
          vrp_signal: "rich",
          vrp_note: "IV rich vs RV — favors short premium",
        }}
      />,
    );
    expect(screen.getByText("IV (ATM)")).toBeDefined();
    expect(screen.getByText(/RICH/)).toBeDefined();
    expect(screen.getByText(/IV rich vs RV/)).toBeDefined();
  });
});

describe("HvIvChart", () => {
  const populated = [
    { date: "2026-05-11", iv: "0.50", rv: "0.40" },
    { date: "2026-05-12", iv: "0.52", rv: "0.41" },
    { date: "2026-05-13", iv: "0.51", rv: "0.42" },
  ];

  it("renders SVG with legend when data is present", () => {
    render(<HvIvChart data={populated} />);
    expect(screen.getByText("— IV")).toBeDefined();
    expect(screen.getByText("— RV")).toBeDefined();
  });

  it("renders empty state when no data", () => {
    render(<HvIvChart data={[]} />);
    expect(screen.getByText(/Insufficient/i)).toBeDefined();
  });

  it("survives partial-null rows without NaN leakage", () => {
    const { container } = render(
      <HvIvChart
        data={[
          { date: "2026-05-11", iv: "0.50", rv: null },
          { date: "2026-05-12", iv: null, rv: "0.41" },
          { date: "2026-05-13", iv: "0.51", rv: "0.42" },
        ]}
      />,
    );
    expect(container.textContent ?? "").not.toMatch(/NaN/);
  });
});

describe("TermStructureChart", () => {
  it("renders ATM line when data is present", () => {
    render(
      <TermStructureChart
        data={[
          {
            expiry: "2026-05-15",
            dte: 2,
            by_strike: { ATM: "0.58", "ATM+1": "0.54" },
          },
          {
            expiry: "2026-05-22",
            dte: 9,
            by_strike: { ATM: "0.55" },
          },
        ]}
      />,
    );
    expect(screen.getByText("— ATM")).toBeDefined();
  });

  it("empty state when fewer than 2 expiries", () => {
    render(<TermStructureChart data={[]} />);
    expect(screen.getByText(/Insufficient/i)).toBeDefined();
  });

  it("partial-null rows do not leak NaN", () => {
    const { container } = render(
      <TermStructureChart
        data={[
          { expiry: "a", dte: 2, by_strike: { ATM: null, "ATM+1": "0.5" } },
          { expiry: "b", dte: 9, by_strike: { ATM: "0.55", "ATM+1": null } },
        ]}
      />,
    );
    expect(container.textContent ?? "").not.toMatch(/NaN/);
  });
});

describe("SmileChart", () => {
  it("renders curves when populated", () => {
    render(
      <SmileChart
        data={[
          {
            expiry: "2026-05-15",
            points: [
              { strike: "400", iv: "0.7" },
              { strike: "405", iv: "0.65" },
            ],
          },
        ]}
      />,
    );
    expect(screen.getByText(/2026-05-15/)).toBeDefined();
  });

  it("empty state when no curves", () => {
    render(<SmileChart data={[]} />);
    expect(screen.getByText(/No smile data/i)).toBeDefined();
  });

  it("partial-null points do not leak NaN", () => {
    const { container } = render(
      <SmileChart
        data={[
          {
            expiry: "x",
            points: [
              { strike: "400", iv: null },
              { strike: "405", iv: "0.65" },
              { strike: "410", iv: "0.6" },
            ],
          },
        ]}
      />,
    );
    expect(container.textContent ?? "").not.toMatch(/NaN/);
  });
});

describe("IvPercentileDistribution", () => {
  it("renders histogram bars", () => {
    render(
      <IvPercentileDistribution
        data={{
          bins: [
            { lo: "0.10", hi: "0.15", count: 12 },
            { lo: "0.15", hi: "0.20", count: 8 },
          ],
          current_iv: "0.16",
          current_pctile: "52",
        }}
      />,
    );
    expect(screen.getByText("52th %ile")).toBeDefined();
  });

  it("empty state when no bins", () => {
    render(<IvPercentileDistribution data={{ bins: [] }} />);
    expect(screen.getByText(/No IV history/i)).toBeDefined();
  });
});

describe("IvOfIvChart", () => {
  it("renders dual-axis with legend", () => {
    render(
      <IvOfIvChart
        data={[
          { date: "a", iv: "0.5", iv_of_iv_20: "0.05" },
          { date: "b", iv: "0.55", iv_of_iv_20: "0.07" },
          { date: "c", iv: "0.52", iv_of_iv_20: "0.06" },
        ]}
      />,
    );
    expect(screen.getByText("— IV (L)")).toBeDefined();
    expect(screen.getByText("— IV-of-IV (R)")).toBeDefined();
  });

  it("partial-null rows do not leak NaN", () => {
    const { container } = render(
      <IvOfIvChart
        data={[
          { date: "a", iv: "0.5", iv_of_iv_20: null },
          { date: "b", iv: null, iv_of_iv_20: "0.07" },
          { date: "c", iv: "0.52", iv_of_iv_20: "0.06" },
        ]}
      />,
    );
    expect(container.textContent ?? "").not.toMatch(/NaN/);
  });
});

describe("RvSpyCorrChart", () => {
  it("renders dual-axis with legend when populated", () => {
    render(
      <RvSpyCorrChart
        data={[
          { date: "a", rv: "0.4", spy_corr_21: "0.3" },
          { date: "b", rv: "0.42", spy_corr_21: "0.35" },
        ]}
      />,
    );
    expect(screen.getByText(/RV \(L\)/)).toBeDefined();
  });

  it("explicit empty state when SPY corr is all null", () => {
    render(
      <RvSpyCorrChart
        data={[
          { date: "a", rv: "0.4", spy_corr_21: null },
          { date: "b", rv: "0.42", spy_corr_21: null },
        ]}
      />,
    );
    expect(screen.getByText(/SPY OHLC not seeded/)).toBeDefined();
  });
});

describe("RegimeQuadrantChart", () => {
  it("highlights latest state tile", () => {
    render(
      <RegimeQuadrantChart
        data={{
          points: [
            { date: "a", rvol_pctile: "20", spy_corr_21: "0.1" },
            { date: "b", rvol_pctile: "30", spy_corr_21: "0.2" },
          ],
          latest: {
            date: "b",
            rvol_pctile: "30",
            spy_corr_21: "0.2",
            state: "GOLDILOCKS",
          },
        }}
      />,
    );
    // "Goldilocks" appears as both the quadrant label and the state tile.
    expect(screen.getAllByText("Goldilocks").length).toBeGreaterThanOrEqual(1);
  });

  it("empty state when no points and no latest", () => {
    render(<RegimeQuadrantChart data={{ points: [], latest: null }} />);
    expect(screen.getByText(/SPY OHLC not seeded/)).toBeDefined();
  });
});

describe("DivergenceOverlay", () => {
  it("renders headline + lines", () => {
    render(
      <DivergenceOverlay
        data={[
          { date: "a", iv_z: "0.5", rv_z: "-0.3" },
          { date: "b", iv_z: "0.6", rv_z: "-0.4" },
        ]}
        headline="+0.9σ"
      />,
    );
    expect(screen.getByText("+0.9σ")).toBeDefined();
  });

  it("partial-null rows do not leak NaN", () => {
    const { container } = render(
      <DivergenceOverlay
        data={[
          { date: "a", iv_z: "0.5", rv_z: null },
          { date: "b", iv_z: null, rv_z: "-0.3" },
          { date: "c", iv_z: "0.6", rv_z: "-0.4" },
        ]}
        headline=""
      />,
    );
    expect(container.textContent ?? "").not.toMatch(/NaN/);
  });
});

describe("VrpSpreadPanel", () => {
  it("renders bars + headline", () => {
    render(
      <VrpSpreadPanel
        data={[
          { date: "a", vrp: "0.05", vrp_z_20: "0.3" },
          { date: "b", vrp: "-0.02", vrp_z_20: "-0.1" },
        ]}
        headline="+0.05 pts | widening +0.07 pts"
      />,
    );
    expect(screen.getByText(/widening/)).toBeDefined();
  });

  it("empty state when no rows", () => {
    render(<VrpSpreadPanel data={[]} />);
    expect(screen.getByText(/No VRP history/i)).toBeDefined();
  });

  it("partial-null bars do not leak NaN", () => {
    const { container } = render(
      <VrpSpreadPanel
        data={[
          { date: "a", vrp: null, vrp_z_20: "0.1" },
          { date: "b", vrp: "0.05", vrp_z_20: null },
          { date: "c", vrp: "0.06", vrp_z_20: "0.2" },
        ]}
      />,
    );
    expect(container.textContent ?? "").not.toMatch(/NaN/);
  });
});
