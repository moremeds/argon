import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { RatesScorecard } from "@/components/rates/RatesScorecard";
import { SNAPSHOT } from "./fixture";

type Scorecard = NonNullable<(typeof SNAPSHOT)["scorecard"]>;

describe("RatesScorecard", () => {
  it("renders server-aligned composite score and static weights", () => {
    render(<RatesScorecard scorecard={SNAPSHOT.scorecard!} />);

    expect(screen.getByTestId("duration-score").textContent).toContain("+0.10");
    expect(screen.getAllByText("Weight 25.00").length).toBeGreaterThan(0);
    expect(screen.queryByLabelText("Monetary Policy weight")).toBeNull();
  });

  it("collapses and expands factor groups", () => {
    render(<RatesScorecard scorecard={SNAPSHOT.scorecard!} />);

    expect(screen.getByText("Policy pressure")).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: /Monetary Policy/ }));

    expect(screen.queryByText("Policy pressure")).toBeNull();
  });

  it("is labelled experimental legacy while dual-read remains", () => {
    render(<RatesScorecard scorecard={SNAPSHOT.scorecard!} />);

    expect(screen.getByTestId("scorecard-legacy-banner").textContent).toMatch(
      /experimental legacy/i,
    );
  });

  it("shows the server stance rather than deriving one from the composite", () => {
    // The two used to be computed independently, so a server refusal and a
    // client-side "NEUTRAL" could sit on the same card.
    const scorecard: Scorecard = {
      ...SNAPSHOT.scorecard!,
      composite_score: 0.9,
      duration_stance: "UNKNOWN",
    };
    render(<RatesScorecard scorecard={scorecard} />);

    expect(screen.getByTestId("duration-stance").textContent).toContain(
      "UNKNOWN",
    );
    expect(screen.queryByText(/BUY duration/)).toBeNull();
  });

  it("refuses a composite when every group is missing instead of printing zero", () => {
    // The bug this replaces: the client renormalised over surviving weight, hit a
    // zero denominator, fell back to 0, and rendered "NEUTRAL duration" — a
    // confident verdict manufactured from nothing at all.
    const scorecard: Scorecard = {
      composite_score: null,
      coverage: 0,
      coverage_detail: "0% of scorecard weight is scored",
      duration_stance: "UNKNOWN",
      curve_stance: "NEUTRAL",
      groups: (SNAPSHOT.scorecard!.groups ?? []).map((group) => ({
        ...group,
        score: null,
        status: "missing" as const,
      })),
    };
    render(<RatesScorecard scorecard={scorecard} />);

    expect(screen.getByTestId("duration-score").textContent).toBe("n/a");
    expect(screen.getByTestId("duration-score").textContent).not.toContain("0");
    expect(screen.getByTestId("scorecard-no-score").textContent).toMatch(
      /No duration stance is taken/,
    );
    expect(screen.queryByText(/NEUTRAL duration/)).toBeNull();
    expect(screen.getAllByText("unscored").length).toBe(
      (SNAPSHOT.scorecard!.groups ?? []).length,
    );
  });
});
