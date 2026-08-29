import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { FedDesk } from "@/components/rates/FedDesk";
import {
  COMPARISON_WITH_REJECTED_PATH,
  POLICY_COMPARISON,
  POLICY_COMPARISON_WITH_MARKET_PATH,
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
  it("matches the artifact's eight-panel inventory and order", () => {
    const { container } = render(
      <FedDesk snapshot={SNAPSHOT} policyComparison={POLICY_COMPARISON} />,
    );
    expect(
      [...container.querySelectorAll(".panel > .panel-h h3")].map(
        (node) => node.textContent,
      ),
    ).toEqual([
      "Four policy paths · who says what",
      "Per-meeting odds · market-implied",
      "Dealer expectations · the 3.63 dot, unrolled",
      "Committee projections · the 3.80 dot, unrolled",
      "State & confidence · the engine's own proof",
      "Plumbing · the balance sheet behind the rate",
      "Next events",
      "What this tab refuses",
    ]);
  });

  it("uses the artifact heading and panel anchors without an extra jump-nav", () => {
    render(<FedDesk snapshot={SNAPSHOT} />);

    const sectionIds = new Set(
      Array.from(document.querySelectorAll('[role="region"][id]')).map(
        (n) => n.id,
      ),
    );
    for (const anchor of [
      "paths",
      "market-implied",
      "dealer-plot",
      "sep-plot",
      "state",
      "policy",
      "events",
      "refuses",
    ]) {
      expect(sectionIds.has(anchor)).toBe(true);
    }
    expect(screen.queryAllByRole("link")).toHaveLength(0);

    // The board's own t1 heading, replacing the "Fed Policy Desk." page lockup: the tab
    // bar one line above already says these words, and the board's tabs open with an
    // `<h2>` + question strip + state pill, not a second page title.
    expect(
      screen.getByRole("heading", { name: "Fed · Policy", level: 2 }),
    ).toBeTruthy();
    expect(screen.getByText("Q1 Q2 Q3 Q5 Q7")).toBeTruthy();
    expect(screen.queryByText(/Snapshot update/)).toBeNull();
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

  it("renders the approved plumbing table without a duplicate futures mini-panel", () => {
    render(<FedDesk snapshot={SNAPSHOT} />);

    const policySection = screen.getByRole("region", {
      name: /plumbing · the balance sheet/i,
    });
    expect(within(policySection).queryByText("Fed funds futures")).toBeNull();
    expect(within(policySection).getByText("ON RRP")).toBeTruthy();
    expect(within(policySection).getByText("0.025 $T")).toBeTruthy();
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

  it("does not add a standalone source-freshness panel absent from the artifact", () => {
    render(<FedDesk snapshot={SNAPSHOT} />);
    expect(screen.queryByRole("region", { name: /source freshness/i })).toBeNull();
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

  it("sizes only positive market buckets while preserving the full publisher distribution", () => {
    render(
      <FedDesk
        snapshot={SNAPSHOT}
        policyComparison={POLICY_COMPARISON_WITH_MARKET_PATH}
      />,
    );

    const bars = screen.getAllByTestId("market-implied-probability-bar");
    expect(bars).toHaveLength(3);

    const first = bars[0];
    expect(first.getAttribute("aria-label")).toContain("Cut 50 bp 0.0%");
    expect(first.getAttribute("aria-label")).toContain("Hike 50 bp 0.0%");

    const segments = Array.from(
      first.querySelectorAll<HTMLElement>("[data-probability-segment]"),
    );
    expect(segments).toHaveLength(2);
    expect(segments.map((segment) => segment.textContent)).toEqual([
      "Hike 25 bp · 55.7 %",
      "Hold · 44.3 %",
    ]);
    expect(segments.map((segment) => segment.style.flexGrow)).toEqual([
      "55.7",
      "44.3",
    ]);
    expect(segments.every((segment) => segment.style.flexBasis === "0px")).toBe(
      true,
    );
  });

  describe("evidence-first presentation", () => {
    const withState = { ...SNAPSHOT, state: POLICY_RATES_STATE };

    it("states the four publishers first, then the engine's reading of them", () => {
      // REVERSED on 2026-08-29, and deliberately. This asserted the opposite — state
      // first, "evidence-first presentation" — which was the port plan's call. The board
      // puts `State & confidence · the engine's own proof` fifth, after all four
      // publisher panels, and where the plan and the board disagree the board wins
      // (CLAUDE.md).
      //
      // The board is also right on the merits: the state is a reading OF those four
      // lanes, and printing it above them invites it to be read as a fifth opinion
      // standing beside the committee's and the dealers' rather than as a verdict on
      // them. "The engine's own proof" only means anything after the reader has seen
      // what it is proving something about.
      const { container } = render(
        <FedDesk snapshot={withState} policyComparison={POLICY_COMPARISON} />,
      );

      const ids = Array.from(
        container.querySelectorAll('[role="region"][id]'),
      ).map((node) => node.id);
      expect(ids.indexOf("paths")).toBe(0);
      expect(ids.indexOf("state")).toBeGreaterThan(ids.indexOf("paths"));
      expect(ids.indexOf("state")).toBeGreaterThan(
        ids.indexOf("market-implied"),
      );
      expect(ids.indexOf("state")).toBeGreaterThan(ids.indexOf("dealer-plot"));
      expect(ids.indexOf("state")).toBeGreaterThan(ids.indexOf("sep-plot"));
      // Still ahead of the mechanics it does not depend on.
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
      expect(screen.getByTestId("rates-state-block").textContent).toMatch(
        /Stood on 9 observations/,
      );
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
      expect(sep.textContent).toContain("3.800");

      const dealer = screen.getByTestId("policy-path-lane-dealer_expectations");
      expect(dealer.textContent).toContain("nyfed_sme");
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
        "policy-path-lane-dealer_expectations",
        "policy-path-lane-committee_projection",
        "policy-path-lane-market_implied",
      ]);
      for (const rate of ["3.50–3.75%", "3.800", "3.630"]) {
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
