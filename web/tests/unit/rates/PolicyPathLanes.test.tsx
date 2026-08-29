import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { PolicyPathComparison } from "@/components/rates/PolicyPathComparison";
import {
  COMPARISON_WITH_REJECTED_PATH,
  POLICY_COMPARISON,
  type PolicyComparison,
} from "./fixture";

function lane(kind: string) {
  return screen.getByTestId(`policy-path-lane-${kind}`);
}

describe("policy path comparison chart", () => {
  it("keeps four publisher lanes separate in one approved chart", () => {
    render(<PolicyPathComparison comparison={POLICY_COMPARISON} />);

    expect(screen.getByTestId("policy-path-comparison").querySelectorAll("svg")).toHaveLength(1);
    for (const kind of [
      "actual",
      "dealer_expectations",
      "committee_projection",
      "market_implied",
    ]) {
      expect(lane(kind)).toBeTruthy();
    }
    expect(screen.getByTestId("policy-path-comparison").textContent).toMatch(
      /never averaged/i,
    );
  });

  it("retains each publisher's source, release and freshness in its SVG lane", () => {
    render(<PolicyPathComparison comparison={POLICY_COMPARISON} />);

    expect(lane("actual").textContent).toMatch(/fomc_statement/);
    expect(lane("actual").textContent).toMatch(/released 2026-06-17/);
    expect(lane("actual").textContent).toMatch(/releases parsed/);
    expect(lane("dealer_expectations").textContent).toMatch(/nyfed_sme/);
  });

  it("distinguishes a missing publisher from rejected non-publisher evidence", () => {
    const { rerender } = render(
      <PolicyPathComparison comparison={POLICY_COMPARISON} />,
    );
    expect(lane("market_implied").getAttribute("data-path-status")).toBe(
      "unavailable",
    );
    expect(lane("market_implied").textContent).toMatch(/not enabled/i);

    rerender(
      <PolicyPathComparison comparison={COMPARISON_WITH_REJECTED_PATH} />,
    );
    expect(lane("actual").getAttribute("data-path-status")).toBe("rejected");
    expect(lane("actual").textContent).toMatch(/Rejected/);
    expect(lane("actual").textContent).not.toContain("3.50–3.75%");
  });

  it("does not print a fictitious 0/0 release ratio for uncatalogued surveys", () => {
    const uncatalogued: PolicyComparison = {
      ...POLICY_COMPARISON,
      dealer_expectations: {
        ...POLICY_COMPARISON.dealer_expectations,
        freshness: {
          ...POLICY_COMPARISON.dealer_expectations.freshness,
          releases_discovered: 0,
          releases_succeeded: 0,
        },
      },
    };
    render(<PolicyPathComparison comparison={uncatalogued} />);

    expect(lane("dealer_expectations").textContent).not.toMatch(
      /0\/0 releases parsed/,
    );
    expect(lane("dealer_expectations").textContent).toMatch(/ok/);
  });
});
