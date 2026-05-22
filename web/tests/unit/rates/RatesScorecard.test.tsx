import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { RatesScorecard } from "@/components/rates/RatesScorecard";
import { SNAPSHOT } from "./fixture";

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
});
