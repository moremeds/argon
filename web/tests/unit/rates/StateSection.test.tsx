import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { StateSection } from "@/components/rates/sections/StateSection";
import { POLICY_RATES_STATE } from "./fixture";

type State = typeof POLICY_RATES_STATE;
type Reason = NonNullable<State["confidence_reasons"]>[number];

function withReasons(reasons: Reason[]): State {
  return { ...POLICY_RATES_STATE, confidence_reasons: reasons };
}

/**
 * The confidence strip replaced a sub-card that listed every term at equal weight.
 * These pin the thing that made the card misleading rather than merely long: a
 * neutral value LOOKS different per term, so a reader could not tell which of six
 * rows had actually moved the number.
 */
describe("StateSection confidence strip", () => {
  it("does not report a penalty at zero as something that reduced confidence", () => {
    // The real shape of a 100%-confidence rates state: the penalties are present and
    // both sit at 0, which is a penalty's NEUTRAL. Read as a multiplicand, 0.00 is
    // total drag -- and that is exactly what the page printed before this: "Reduced
    // by revision penalty x0.00", on a state nothing had reduced.
    render(
      <StateSection
        state={withReasons([
          {
            term: "completeness",
            value: "1",
            detail: "3/3 load-bearing inputs present",
            kind: "multiplicand",
          },
          {
            term: "revision_penalty",
            value: "0",
            detail: "no load-bearing input revised since the prior state",
            kind: "penalty",
          },
          {
            term: "contradiction_penalty",
            value: "0.00",
            detail: "0 rule(s) fired: none",
            kind: "penalty",
          },
        ])}
      />,
    );

    const strip = screen.getByTestId("rates-confidence-strip");
    expect(strip.textContent).toContain("Nothing reduced it");
    expect(strip.textContent).not.toContain("Reduced by");
  });

  it("names a penalty that is actually biting, and a multiplicand below one", () => {
    render(
      <StateSection
        state={withReasons([
          {
            term: "completeness",
            value: "0.67",
            detail:
              "2/3 load-bearing inputs present; missing SEP_FEDERAL_FUNDS_RATE",
            kind: "multiplicand",
          },
          {
            term: "contradiction_penalty",
            value: "0.20",
            detail: "2 rule(s) fired: dealer_vs_committee, curve_vs_policy",
            kind: "penalty",
          },
        ])}
      />,
    );

    const strip = screen.getByTestId("rates-confidence-strip");
    expect(strip.textContent).toContain("Reduced by");
    expect(strip.textContent).toMatch(/completeness/i);
    expect(strip.textContent).toMatch(/contradiction penalty/i);
    expect(strip.textContent).not.toContain("Nothing reduced it");
  });

  it("keeps an informational term out of the drag list whatever its value", () => {
    // market_factors_absent carries a COUNT (3 absent factor groups). It is not in
    // the confidence product at all, so ranking it beside the multiplicands invited
    // reading "x3.00" as a term that tripled the number it only annotates.
    render(
      <StateSection
        state={withReasons([
          {
            term: "completeness",
            value: "1",
            detail: "3/3 load-bearing inputs present",
            kind: "multiplicand",
          },
          {
            term: "market_factors_absent",
            value: "3",
            detail: "no observations for: supply, positioning, plumbing",
            kind: "informational",
          },
        ])}
      />,
    );

    const strip = screen.getByTestId("rates-confidence-strip");
    expect(strip.textContent).toContain("Nothing reduced it");
    // Still shown -- it is the one genuinely informative line -- just not as a drag.
    expect(strip.textContent).toMatch(/market factors absent/i);
    expect(strip.textContent).toContain("supply, positioning, plumbing");
  });

  it("does not repeat the section heading as an eyebrow above the state", () => {
    render(<StateSection state={POLICY_RATES_STATE} />);

    const block = screen.getByTestId("rates-state-block");
    expect(block.textContent).not.toMatch(/policy \/ rates state/i);
    // Engine identity remains available for audit without becoming display copy.
    expect(block.getAttribute("data-engine-version")).toBe(
      POLICY_RATES_STATE.engine_version,
    );
  });
});
