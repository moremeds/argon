import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { FedDesk } from "@/components/rates/FedDesk";
import {
  COMPARISON_WITH_REJECTED_PATH,
  POLICY_COMPARISON,
  POLICY_RATES_STATE,
  SNAPSHOT,
  STALE_POLICY_RATES_STATE,
} from "./fixture";

/**
 * Macro desk tab 01. Half of what `RatesDesk.test.tsx` covered before the split; the
 * market half moved to `CurveDesk.test.tsx`, and three subjects were deleted outright by
 * the §7 settlement (the stance cards, the synthesis prose, and the composite's
 * narration).
 */
describe("FedDesk", () => {
  it("renders its own anchors and no anchor belonging to the curve tab", () => {
    render(<FedDesk snapshot={SNAPSHOT} />);

    for (const label of [
      "State",
      "Four lanes",
      "Dot plot",
      "Dealer path",
      "Policy",
      "Events",
      "Refusals",
      "Sources",
    ]) {
      expect(screen.getByRole("link", { name: label })).toBeTruthy();
    }

    // Each tab's NAV covers only its own sections, so an anchor to a section this tab
    // does not render would be a link to nowhere.
    for (const label of [
      "Summary",
      "Curve",
      "Decomposition",
      // Issuance moved to tab 02 on 2026-08-28 -- the board assigns supply and auction
      // demand to the curve. An anchor left here would point at a section this tab no
      // longer renders.
      "Supply",
      "Positioning",
      "Cross-market",
    ]) {
      expect(screen.queryByRole("link", { name: label })).toBeNull();
    }

    for (const tier of ["The answer", "Who says what", "Mechanics"]) {
      expect(screen.getByRole("link", { name: tier })).toBeTruthy();
      expect(screen.getByRole("heading", { name: tier })).toBeTruthy();
    }

    // The board's own t1 heading, replacing the "Fed Policy Desk." page lockup: the tab
    // bar one line above already says these words, and the board's tabs open with an
    // `<h2>` + question strip + state pill, not a second page title.
    expect(
      screen.getByRole("heading", { name: "Fed · Policy", level: 2 }),
    ).toBeTruthy();
    for (const q of ["Q1", "Q2", "Q3", "Q5", "Q7"]) {
      expect(screen.getByText(q)).toBeTruthy();
    }
    expect(
      screen.getByText(/Snapshot update · .* HKT · FRED as of 2026-05-20/),
    ).toBeTruthy();
  });

  it("shows the tab's state on the board's pill, in both of its states", () => {
    // The board puts a state pill on t1's title row. It is three-state for the same
    // reason the domain tabs' is: a state that was never computed is a different fact
    // from one this desk simply is not showing, and an absent answer must never be able
    // to look like an answer — so the empty pill stays neutral and says so in words.
    const { unmount } = render(<FedDesk snapshot={SNAPSHOT} />);
    const empty = screen.getByTestId("rates-desk-state-pill");
    expect(empty.textContent).toContain("the engine has not run");
    expect(empty.className).toContain("neust");
    unmount();

    render(<FedDesk snapshot={{ ...SNAPSHOT, state: POLICY_RATES_STATE }} />);
    const filled = screen.getByTestId("rates-desk-state-pill");
    // The board's own format: LABEL · DIRECTION · conf N.NN.
    expect(filled.textContent).toBe("ON_HOLD · FLAT · conf 0.62");
    // ON_HOLD is not a verdict, so it is not coloured. Only the two labels that name
    // their own distance from a target are.
    expect(filled.className).toContain("neust");
  });

  it("renders futures move probabilities and low ON RRP in trillions", () => {
    render(<FedDesk snapshot={SNAPSHOT} />);

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

  it("states its refusals, including the one this tab exists to need", () => {
    // The board gives every tab a refusal panel and this was the only one of the five
    // shipping without it. It matters most here: this is the tab carrying four separately
    // published paths, and averaging them is the single most natural wrong thing to do
    // with the page.
    render(<FedDesk snapshot={SNAPSHOT} />);

    const refuses = screen.getByRole("region", {
      name: /what this tab refuses/i,
    });
    expect(refuses.textContent).toMatch(/No averaging of the four paths/i);
    expect(refuses.textContent).toMatch(/dots stay anonymous/i);
    expect(refuses.textContent).toMatch(/short column is printed short/i);
  });

  it("no longer renders issuance, which belongs to the curve tab", () => {
    render(<FedDesk snapshot={SNAPSHOT} />);
    expect(screen.queryByRole("region", { name: /^supply$/i })).toBeNull();
    expect(screen.queryByText("Recent auctions")).toBeNull();
  });

  it("renders source freshness so failed refreshes do not look live", () => {
    // Provenance for the one snapshot this tab already fetched. It renders on both
    // tabs on purpose: the policy and supply panels here read the same FRED feed, so
    // hiding it would make a stale publisher invisible on the tab that depends on it.
    render(<FedDesk snapshot={SNAPSHOT} />);

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

  it("renders an explicit empty state when no snapshot exists", () => {
    render(<FedDesk snapshot={null} />);

    expect(screen.getByText(/Rates snapshot not computed/)).toBeTruthy();
  });

  it("renders an explicit API outage state separately from a missing snapshot", () => {
    render(
      <FedDesk snapshot={null} errorMessage="The rates API request failed" />,
    );

    expect(screen.getByText(/Rates API unavailable/)).toBeTruthy();
    expect(screen.getByText(/The rates API request failed/)).toBeTruthy();
  });

  describe("evidence-first presentation", () => {
    const withState = { ...SNAPSHOT, state: POLICY_RATES_STATE };

    it("leads with the domain state, ahead of the publishers who feed it", () => {
      const { container } = render(
        <FedDesk snapshot={withState} policyComparison={POLICY_COMPARISON} />,
      );

      const ids = Array.from(container.querySelectorAll("section[id]")).map(
        (node) => node.id,
      );
      expect(ids.indexOf("state")).toBe(0);
      expect(ids.indexOf("paths")).toBe(1);
      expect(ids.indexOf("state")).toBeLessThan(ids.indexOf("policy"));
    });

    it("shows state, direction, velocity, confidence reasons, and contradictions", () => {
      render(
        <FedDesk snapshot={withState} policyComparison={POLICY_COMPARISON} />,
      );

      expect(screen.getByTestId("rates-state-label").textContent).toBe(
        "ON HOLD",
      );
      expect(screen.getByTestId("rates-state-direction").textContent).toContain(
        "FLAT",
      );
      expect(screen.getByTestId("rates-state-confidence").textContent).toBe(
        "62%",
      );
      expect(screen.getByText("target_range_midpoint_change")).toBeTruthy();
      // A velocity that could not be computed says why instead of showing 0.00.
      expect(
        screen.getByText("DFII10 has no observation in force at this instant."),
      ).toBeTruthy();
      expect(
        screen.getByText("3 of 4 policy paths carry a release."),
      ).toBeTruthy();
      expect(
        within(screen.getByTestId("rates-state-contradictions")).getByText(
          /17bp above the dealer median/,
        ),
      ).toBeTruthy();
      expect(screen.getByText(/Stood on 9 observations/)).toBeTruthy();
    });

    it("says a state was not computed rather than showing a neutral one", () => {
      render(
        <FedDesk snapshot={SNAPSHOT} policyComparison={POLICY_COMPARISON} />,
      );

      const missing = screen.getByTestId("rates-state-missing");
      expect(missing.textContent).toContain("Not computed");
      expect(screen.queryByTestId("rates-state-block")).toBeNull();
      expect(missing.textContent).not.toMatch(/NEUTRAL/);
      // The refusal must not point at a panel this tab does not carry: the legacy rule
      // score is quarantined on the curve tab, not below this section.
      expect(missing.textContent).not.toMatch(/scorecard below/i);
    });

    it("labels a state nobody has recomputed as stale, still showing what it said", () => {
      render(
        <FedDesk
          snapshot={{ ...SNAPSHOT, state: STALE_POLICY_RATES_STATE }}
          policyComparison={POLICY_COMPARISON}
        />,
      );

      expect(screen.getByTestId("rates-state-freshness").textContent).toMatch(
        /Stale · 96\.0h/,
      );
      expect(screen.getByTestId("rates-state-label").textContent).toBe(
        "ON HOLD",
      );
    });
  });

  describe("policy path lanes", () => {
    it("renders four lanes, each with its own source and release date", () => {
      render(
        <FedDesk snapshot={SNAPSHOT} policyComparison={POLICY_COMPARISON} />,
      );

      const lanes = screen
        .getByTestId("policy-path-comparison")
        .querySelectorAll('[data-testid^="policy-path-lane-"]');
      expect(lanes.length).toBe(4);

      const actual = screen.getByTestId("policy-path-lane-actual");
      expect(actual.textContent).toContain("fomc_statement");
      expect(actual.textContent).toContain("released 2026-06-17");
      expect(actual.textContent).toContain("3.50–3.75%");
      expect(actual.textContent).toContain("Hold");

      const sep = screen.getByTestId("policy-path-lane-committee_projection");
      expect(sep.textContent).toContain("fed_sep");
      expect(sep.textContent).toContain("3.80 %");
      // Horizon detail lives in the dot plot below; the lane keeps the near-term
      // number and points at the chart rather than rendering the release twice.
      expect(sep.textContent).toContain("plotted below");

      const dealer = screen.getByTestId("policy-path-lane-dealer_expectations");
      expect(dealer.textContent).toContain("nyfed_sme");
      expect(dealer.textContent).toContain("plotted below");
      // Respondent counts moved to the chart's note ("n varies by horizon, ...")
      // along with the per-horizon rows. The lane keeps the release identity, which
      // is the thing only a lane shows.
      expect(dealer.textContent).toContain("released");
    });

    it("never merges the paths into a single Fed path", () => {
      render(
        <FedDesk snapshot={SNAPSHOT} policyComparison={POLICY_COMPARISON} />,
      );

      const block = screen.getByTestId("policy-path-comparison");
      expect(block.textContent).toMatch(/never averaged/i);

      // The structural version of the rule: every published rate belongs to exactly
      // one lane. A merged path would have to show a value in more than one, or
      // introduce a fifth lane carrying a number nobody published.
      const lanes = Array.from(
        block.querySelectorAll('[data-testid^="policy-path-lane-"]'),
      );
      expect(lanes.map((lane) => lane.getAttribute("data-testid"))).toEqual([
        "policy-path-lane-actual",
        "policy-path-lane-committee_projection",
        "policy-path-lane-dealer_expectations",
        "policy-path-lane-market_implied",
      ]);
      for (const rate of ["3.50–3.75%", "3.80 %", "3.63 %"]) {
        expect(
          lanes.filter((lane) => (lane.textContent ?? "").includes(rate))
            .length,
        ).toBe(1);
      }
    });

    it("never attributes an anonymous SEP dot to a named participant", () => {
      render(
        <FedDesk snapshot={SNAPSHOT} policyComparison={POLICY_COMPARISON} />,
      );

      const sep = screen.getByTestId("policy-path-lane-committee_projection");
      expect(screen.getByTestId("sep-anonymity-note").textContent).toMatch(
        /dots are anonymous/i,
      );
      // The dot COUNT moved to the plot with the rest of the per-horizon detail.
      // What must not move is the sentence: the anonymity rule is stated wherever
      // the desk shows these dots, which is why it survives the collapsed lane.
      expect(sep.textContent).toMatch(/anonymous/i);
      expect(sep.textContent).not.toMatch(/chair|powell/i);
    });

    it("keeps an empty roster distinct from a unanimous vote", () => {
      // The real 2026-06 statement prints "12-0" and names nobody, so an empty
      // voted_against means only that no dissenter was named.
      render(
        <FedDesk snapshot={SNAPSHOT} policyComparison={POLICY_COMPARISON} />,
      );

      const actual = screen.getByTestId("policy-path-lane-actual");
      expect(actual.textContent).toContain("Vote 12-0");
      expect(actual.textContent).toContain("no dissenter named");
      expect(actual.textContent).not.toContain("no dissent ·");
    });

    it("renders a missing path with its reason instead of a blank lane", () => {
      render(
        <FedDesk snapshot={SNAPSHOT} policyComparison={POLICY_COMPARISON} />,
      );

      const market = screen.getByTestId("policy-path-lane-market_implied");
      expect(market.getAttribute("data-path-status")).toBe("unavailable");
      expect(market.textContent).toContain(
        "optional third-party shadow and is not enabled",
      );
    });

    it("withholds the numbers of a path carrying a non-publisher source", () => {
      render(
        <FedDesk
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
        <FedDesk
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

  describe("the §7 settlement", () => {
    const withState = { ...SNAPSHOT, state: POLICY_RATES_STATE };

    it("prescribes nothing: no stance card, no BUY/SELL anywhere in the tab", () => {
      const { container } = render(
        <FedDesk snapshot={withState} policyComparison={POLICY_COMPARISON} />,
      );

      expect(screen.queryByTestId("legacy-stance-grid")).toBeNull();
      expect(screen.queryByText("Duration stance")).toBeNull();
      expect(screen.queryByText("Curve stance")).toBeNull();
      expect(container.textContent ?? "").not.toMatch(/\b(BUY|SELL)\b/);
    });

    it("does not narrate the composite: the synthesis prose is gone", () => {
      const { container } = render(
        <FedDesk snapshot={withState} policyComparison={POLICY_COMPARISON} />,
      );

      const text = container.textContent ?? "";
      expect(text).not.toContain(SNAPSHOT.synthesis.duration_view);
      expect(text).not.toContain(SNAPSHOT.synthesis.curve_view);
      for (const risk of SNAPSHOT.synthesis.risks ?? []) {
        expect(text).not.toContain(risk);
      }
    });

    it("keeps the quarantined legacy scorecard off this tab entirely", () => {
      render(
        <FedDesk snapshot={withState} policyComparison={POLICY_COMPARISON} />,
      );

      expect(screen.queryByTestId("rates-scorecard")).toBeNull();
    });
  });
});
