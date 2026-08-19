import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { RatesDesk } from "@/components/rates/RatesDesk";
import {
  COMPARISON_WITH_REJECTED_PATH,
  POLICY_COMPARISON,
  POLICY_RATES_STATE,
  SNAPSHOT,
  STALE_POLICY_RATES_STATE,
  TENORS,
} from "./fixture";

describe("RatesDesk", () => {
  it("renders all reference-page anchors and KPI tiles", () => {
    render(<RatesDesk snapshot={SNAPSHOT} />);

    for (const label of [
      "State",
      "Policy Paths",
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
    expect(
      screen.getAllByText("Curve still biased flatter.").length,
    ).toBeGreaterThan(1);
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
    expect(screen.getByText(/the bills-to-10Y spread is wide/)).toBeTruthy();
    expect(screen.getByText(/Belly is rich versus wings/)).toBeTruthy();
  });

  it("never describes a curve slope as a term premium", () => {
    // A slope is a difference between two traded yields. Term premium is a model
    // output, and the only one on this page belongs to the Cleveland Fed section.
    const { container } = render(<RatesDesk snapshot={SNAPSHOT} />);
    const slopeCards = container.querySelectorAll('[data-testid="slope-card"]');
    const slopeText = Array.from(slopeCards)
      .map((node) => node.textContent ?? "")
      .join(" ");
    expect(slopeText.toLowerCase()).not.toContain("term premium");
  });

  it("renders a live decomposition dashboard with attribution rows", () => {
    render(<RatesDesk snapshot={SNAPSHOT} />);

    expect(
      screen.getByText(
        "Live 10Y nominal = E[short real] + E[short inflation] + real term premium + inflation risk premium + Cleveland/FRED gap",
      ),
    ).toBeTruthy();
    expect(
      screen.getByText(/Cleveland Fed model \+ FRED DGS10 · 2026-05-01/),
    ).toBeTruthy();
    expect(screen.getByText("Live 10Y nominal")).toBeTruthy();
    expect(screen.getByText("Expected short real")).toBeTruthy();
    expect(
      screen.getAllByText("Expected short inflation").length,
    ).toBeGreaterThan(1);
    expect(screen.getAllByText("Real term premium").length).toBeGreaterThan(1);
    expect(
      screen.getAllByText("Inflation risk premium").length,
    ).toBeGreaterThan(1);
    expect(screen.getAllByText("FRED residual").length).toBeGreaterThan(1);
    expect(screen.getByText("Cleveland/FRED gap")).toBeTruthy();
    expect(screen.getByText(/reconciliation term that bridges/)).toBeTruthy();
    expect(screen.getByText("Move attribution · bps")).toBeTruthy();
    expect(screen.getAllByText("+15.3").length).toBeGreaterThan(0);
    expect(screen.getAllByText("+19.7").length).toBeGreaterThan(0);
    expect(
      screen.getByText(/expected inflation contributes 5\.7 bps/),
    ).toBeTruthy();
    expect(screen.getByText("Rates read")).toBeTruthy();
    expect(
      screen.getByText(/Cleveland's monthly model explains \+15\.3 bps/),
    ).toBeTruthy();
    expect(
      screen.getByText(
        /daily FRED pricing has moved faster than the monthly Cleveland release/,
      ),
    ).toBeTruthy();
  });

  it("renders persisted Treasury supply data instead of the phase placeholder", () => {
    render(<RatesDesk snapshot={SNAPSHOT} />);

    const supplySection = screen.getByRole("region", { name: /supply/i });
    expect(within(supplySection).getByText("Recent auctions")).toBeTruthy();
    expect(within(supplySection).getByText("30-Year Bond")).toBeTruthy();
    expect(within(supplySection).getByText("$25.0bn")).toBeTruthy();
    expect(within(supplySection).getByText("2.30")).toBeTruthy();
    expect(within(supplySection).getByText("Public debt")).toBeTruthy();
    expect(within(supplySection).getByText("$31.37T")).toBeTruthy();
    expect(screen.queryByText(/Treasury auction feed not wired/)).toBeNull();
    expect(screen.queryByText(/CFTC\/TIC feeds not wired/)).toBeNull();
  });

  it("renders persisted CFTC TFF positioning detail", () => {
    render(<RatesDesk snapshot={SNAPSHOT} />);

    const positioningSection = screen.getByRole("region", {
      name: /positioning/i,
    });
    expect(
      within(positioningSection).getByText("Leveraged funds · long end"),
    ).toBeTruthy();
    expect(within(positioningSection).getByText("UST 10Y NOTE")).toBeTruthy();
    expect(within(positioningSection).getByText("-26.3% OI")).toBeTruthy();
    expect(
      within(positioningSection).getByText(/CFTC TFF 2026-05-22/),
    ).toBeTruthy();
  });

  it("renders source freshness so failed refreshes do not look live", () => {
    render(<RatesDesk snapshot={SNAPSHOT} />);

    expect(screen.getByText("10Y Treasury")).toBeTruthy();
    expect(
      screen.getByText("Cleveland Fed 10Y expected inflation"),
    ).toBeTruthy();
    expect(screen.getByText("Stale")).toBeTruthy();
    expect(screen.getByText("FRED / Board of Governors")).toBeTruthy();
    expect(
      screen.getByText("Cleveland Fed Inflation Expectations"),
    ).toBeTruthy();
    expect(screen.getByRole("link", { name: "FRED DGS10" })).toHaveProperty(
      "href",
      "https://fred.stlouisfed.org/series/DGS10",
    );
    expect(
      screen.getByRole("link", {
        name: "Cleveland Fed CLEVE_EXPECTED_INFLATION_10Y",
      }),
    ).toHaveProperty(
      "href",
      "https://www.clevelandfed.org/indicators-and-data/inflation-expectations",
    );
  });

  it("renders futures move probabilities and low ON RRP in trillions", () => {
    render(<RatesDesk snapshot={SNAPSHOT} />);

    const policySection = screen.getByRole("region", { name: /^policy$/i });
    expect(within(policySection).getByText("Fed funds futures")).toBeTruthy();
    expect(within(policySection).getByText("6/17")).toBeTruthy();
    expect(within(policySection).getByText("7/29")).toBeTruthy();
    expect(
      within(policySection).getByText(
        "Frenzy Capital Fed Watch assigns 53.9% to hold at the next meeting.",
      ),
    ).toBeTruthy();
    expect(within(policySection).getByText("$0.025T")).toBeTruthy();
  });

  it("renders an explicit empty state when no snapshot exists", () => {
    render(<RatesDesk snapshot={null} />);

    expect(screen.getByText(/Rates snapshot not computed/)).toBeTruthy();
  });

  describe("evidence-first presentation", () => {
    const withState = { ...SNAPSHOT, state: POLICY_RATES_STATE };

    it("leads with the domain state, ahead of the legacy summary", () => {
      const { container } = render(
        <RatesDesk snapshot={withState} policyComparison={POLICY_COMPARISON} />,
      );

      const ids = Array.from(container.querySelectorAll("section[id]")).map(
        (node) => node.id,
      );
      expect(ids.indexOf("state")).toBe(0);
      expect(ids.indexOf("paths")).toBe(1);
      expect(ids.indexOf("state")).toBeLessThan(ids.indexOf("summary"));
      expect(ids.indexOf("state")).toBeLessThan(ids.indexOf("scorecard"));
    });

    it("shows state, direction, velocity, confidence reasons, and contradictions", () => {
      render(<RatesDesk snapshot={withState} policyComparison={POLICY_COMPARISON} />);

      expect(screen.getByTestId("rates-state-label").textContent).toBe("ON HOLD");
      expect(screen.getByTestId("rates-state-direction").textContent).toContain(
        "FLAT",
      );
      expect(screen.getByTestId("rates-state-confidence").textContent).toBe("62%");
      expect(screen.getByText("target_range_midpoint_change")).toBeTruthy();
      // A velocity that could not be computed says why instead of showing 0.00.
      expect(
        screen.getByText("DFII10 has no observation in force at this instant."),
      ).toBeTruthy();
      expect(screen.getByText("3 of 4 policy paths carry a release.")).toBeTruthy();
      expect(
        within(screen.getByTestId("rates-state-contradictions")).getByText(
          /17bp above the dealer median/,
        ),
      ).toBeTruthy();
      expect(screen.getByText(/Stood on 9 observations/)).toBeTruthy();
    });

    it("says a state was not computed rather than showing a neutral one", () => {
      render(<RatesDesk snapshot={SNAPSHOT} policyComparison={POLICY_COMPARISON} />);

      const missing = screen.getByTestId("rates-state-missing");
      expect(missing.textContent).toContain("Not computed");
      expect(screen.queryByTestId("rates-state-block")).toBeNull();
      expect(missing.textContent).not.toMatch(/NEUTRAL/);
    });

    it("labels a state nobody has recomputed as stale, still showing what it said", () => {
      render(
        <RatesDesk
          snapshot={{ ...SNAPSHOT, state: STALE_POLICY_RATES_STATE }}
          policyComparison={POLICY_COMPARISON}
        />,
      );

      expect(screen.getByTestId("rates-state-freshness").textContent).toMatch(
        /Stale · 96\.0h/,
      );
      expect(screen.getByTestId("rates-state-label").textContent).toBe("ON HOLD");
    });

    it("demotes the legacy composite and stances behind an experimental label", () => {
      render(<RatesDesk snapshot={withState} policyComparison={POLICY_COMPARISON} />);

      expect(screen.getAllByText(/Experimental legacy/).length).toBeGreaterThan(1);
      expect(screen.getByTestId("legacy-stance-grid")).toBeTruthy();
    });
  });

  describe("policy path lanes", () => {
    it("renders four lanes, each with its own source and release date", () => {
      render(<RatesDesk snapshot={SNAPSHOT} policyComparison={POLICY_COMPARISON} />);

      const lanes = screen
        .getByTestId("policy-path-comparison")
        .querySelectorAll("[data-testid^=\"policy-path-lane-\"]");
      expect(lanes.length).toBe(4);

      const actual = screen.getByTestId("policy-path-lane-actual");
      expect(actual.textContent).toContain("fomc_statement");
      expect(actual.textContent).toContain("released 2026-06-17");
      expect(actual.textContent).toContain("3.50–3.75%");
      expect(actual.textContent).toContain("Hold");

      const sep = screen.getByTestId("policy-path-lane-committee_projection");
      expect(sep.textContent).toContain("fed_sep");
      expect(sep.textContent).toContain("3.80 %");
      expect(sep.textContent).toContain("central tendency 3.60–4.10%");

      const dealer = screen.getByTestId("policy-path-lane-dealer_expectations");
      expect(dealer.textContent).toContain("nyfed_sme");
      expect(dealer.textContent).toContain("IQR 3.44–3.63%");
      expect(dealer.textContent).toContain("n=26");
    });

    it("never merges the paths into a single Fed path", () => {
      render(<RatesDesk snapshot={SNAPSHOT} policyComparison={POLICY_COMPARISON} />);

      const block = screen.getByTestId("policy-path-comparison");
      expect(block.textContent).toMatch(/never averaged/i);

      // The structural version of the rule: every published rate belongs to exactly
      // one lane. A merged path would have to show a value in more than one, or
      // introduce a fifth lane carrying a number nobody published.
      const lanes = Array.from(
        block.querySelectorAll("[data-testid^=\"policy-path-lane-\"]"),
      );
      expect(lanes.map((lane) => lane.getAttribute("data-testid"))).toEqual([
        "policy-path-lane-actual",
        "policy-path-lane-committee_projection",
        "policy-path-lane-dealer_expectations",
        "policy-path-lane-market_implied",
      ]);
      for (const rate of ["3.50–3.75%", "3.80 %", "3.63 %"]) {
        expect(
          lanes.filter((lane) => (lane.textContent ?? "").includes(rate)).length,
        ).toBe(1);
      }
    });

    it("never attributes an anonymous SEP dot to a named participant", () => {
      render(<RatesDesk snapshot={SNAPSHOT} policyComparison={POLICY_COMPARISON} />);

      const sep = screen.getByTestId("policy-path-lane-committee_projection");
      expect(screen.getByTestId("sep-anonymity-note").textContent).toMatch(
        /dots are anonymous/i,
      );
      expect(sep.textContent).toContain("18 dots");
      expect(sep.textContent).not.toMatch(/chair|powell/i);
    });

    it("keeps an empty roster distinct from a unanimous vote", () => {
      // The real 2026-06 statement prints "12-0" and names nobody, so an empty
      // voted_against means only that no dissenter was named.
      render(<RatesDesk snapshot={SNAPSHOT} policyComparison={POLICY_COMPARISON} />);

      const actual = screen.getByTestId("policy-path-lane-actual");
      expect(actual.textContent).toContain("Vote 12-0");
      expect(actual.textContent).toContain("no dissenter named");
      expect(actual.textContent).not.toContain("no dissent ·");
    });

    it("renders a missing path with its reason instead of a blank lane", () => {
      render(<RatesDesk snapshot={SNAPSHOT} policyComparison={POLICY_COMPARISON} />);

      const market = screen.getByTestId("policy-path-lane-market_implied");
      expect(market.getAttribute("data-path-status")).toBe("unavailable");
      expect(market.textContent).toContain(
        "optional third-party shadow and is not enabled",
      );
    });

    it("withholds the numbers of a path carrying a non-publisher source", () => {
      render(
        <RatesDesk
          snapshot={SNAPSHOT}
          policyComparison={COMPARISON_WITH_REJECTED_PATH}
        />,
      );

      const actual = screen.getByTestId("policy-path-lane-actual");
      expect(actual.getAttribute("data-path-status")).toBe("rejected");
      expect(actual.textContent).toMatch(/Rejected/);
      expect(actual.textContent).not.toContain("3.50–3.75%");
    });

    it("states why the paths are absent when the macro API fails", () => {
      render(
        <RatesDesk
          snapshot={SNAPSHOT}
          policyComparison={null}
          policyComparisonError="The macro policy API request failed: API 503"
        />,
      );

      expect(screen.getByTestId("policy-paths-missing").textContent).toContain(
        "API 503",
      );
    });
  });

  it("renders an explicit API outage state separately from a missing snapshot", () => {
    render(
      <RatesDesk snapshot={null} errorMessage="The rates API request failed" />,
    );

    expect(screen.getByText(/Rates API unavailable/)).toBeTruthy();
    expect(screen.getByText(/The rates API request failed/)).toBeTruthy();
  });
});
