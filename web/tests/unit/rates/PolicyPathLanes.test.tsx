import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { PolicyPathComparison } from "@/components/rates/PolicyPathComparison";
import { POLICY_COMPARISON, type PolicyComparison } from "./fixture";

function lane(kind: string) {
  return screen.getByTestId(`policy-path-lane-${kind}`);
}

describe("policy path lanes", () => {
  it("defers a charted lane's horizons to the chart instead of listing them twice", () => {
    render(<PolicyPathComparison comparison={POLICY_COMPARISON} />);

    // The SEP and dealer paths are plotted in full directly below. Listing every
    // horizon here as well rendered one release twice, and the taller of the two
    // renderings is the one that hides its shape.
    for (const kind of ["committee_projection", "dealer_expectations"]) {
      const summary = within(lane(kind)).getByTestId("policy-path-summary");
      expect(summary.textContent).toMatch(/horizons? plotted below/);
    }

    // The two lanes with no chart still show their numbers here — there is nowhere
    // else for them to appear.
    expect(
      within(lane("actual")).queryByTestId("policy-path-summary"),
    ).toBeNull();
  });

  it("explains a lane whose newest release predates the newest FOMC decision", () => {
    // The real shape this exists for: the committee met on 2026-07-29 and published
    // no projections, because it publishes them at four of its eight annual
    // meetings. An SEP dated a meeting earlier is correct, and without a sentence
    // saying so the reader diagnoses a data outage that is not happening.
    const actualMovedOn: PolicyComparison = {
      ...POLICY_COMPARISON,
      actual: {
        ...POLICY_COMPARISON.actual,
        path: {
          ...POLICY_COMPARISON.actual.path!,
          release_date: "2026-07-29",
        },
      },
    };
    render(<PolicyPathComparison comparison={actualMovedOn} />);

    const note = within(lane("committee_projection")).getByTestId(
      "policy-path-behind",
    );
    expect(note.textContent).toMatch(/No release since 2026-06-17/);
    expect(note.textContent).toMatch(/FOMC last decided on 2026-07-29/);

    // The actual lane is the reference; it can never be behind itself.
    expect(
      within(lane("actual")).queryByTestId("policy-path-behind"),
    ).toBeNull();
  });

  it("goes quiet when the lane is level with the newest decision", () => {
    // Same release date on both: nothing to explain, so nothing is said.
    render(<PolicyPathComparison comparison={POLICY_COMPARISON} />);
    const sep = POLICY_COMPARISON.committee_projection.path!;
    const actual = POLICY_COMPARISON.actual.path!;
    expect(sep.published_at?.slice(0, 10)).toBe(
      actual.published_at?.slice(0, 10),
    );
    expect(
      within(lane("committee_projection")).queryByTestId("policy-path-behind"),
    ).toBeNull();
  });

  it("hides a release ratio the catalog does not model rather than printing 0/0", () => {
    // The per-release catalog covers FOMC statements and SEPs only; the dealer
    // survey carries release_type=None by design, so its counters are structurally
    // 0/0. Printed anyway, "0/0 releases parsed" sat under a lane showing twelve
    // parsed surveys and read as a broken feed.
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
    // The status itself is still reported — it is the part that is true.
    expect(lane("dealer_expectations").textContent).toMatch(/ok/);
    // A lane the catalog does model keeps its ratio.
    expect(lane("actual").textContent).toMatch(/\d+\/\d+ releases parsed/);
  });
});
