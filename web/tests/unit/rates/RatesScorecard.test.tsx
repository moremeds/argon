import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { RatesScorecard } from "@/components/rates/RatesScorecard";
import { SNAPSHOT } from "./fixture";

describe("RatesScorecard", () => {
  it("recalculates the composite score when weights change", () => {
    render(<RatesScorecard scorecard={SNAPSHOT.scorecard!} />);

    expect(screen.getByTestId("duration-score").textContent).toContain("0.00");

    fireEvent.change(screen.getByLabelText("Monetary Policy weight"), {
      target: { value: "100" },
    });

    expect(screen.getByTestId("duration-score").textContent).toContain("-0.60");
  });

  it("collapses and expands factor groups", () => {
    render(<RatesScorecard scorecard={SNAPSHOT.scorecard!} />);

    expect(screen.getByText("Policy pressure")).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: /Monetary Policy/ }));

    expect(screen.queryByText("Policy pressure")).toBeNull();
  });
});
