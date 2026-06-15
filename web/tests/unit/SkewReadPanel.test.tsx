import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { SkewReadPanel } from "@/components/stock/panels/SkewReadPanel";

const base = {
  summary_line: "RICH put-skew",
  class_context: "single_name (expected mixed)",
  borrow_context: "normal",
  earnings_gate: "pass",
};

describe("SkewReadPanel", () => {
  it("renders a bearish lean with confidence and express", () => {
    render(
      <SkewReadPanel
        read={{
          ...base,
          directional_lean: {
            lean: "BEARISH_TILT",
            confidence: "med",
            basis: "validated — separated -2.1%/20d",
            express: "put-debit-spread",
          },
        }}
      />,
    );
    expect(screen.getByText("BEARISH")).toBeTruthy();
    expect(screen.getByText(/confidence: med/)).toBeTruthy();
    expect(screen.getByText(/put-debit-spread/)).toBeTruthy();
  });

  it("renders NEUTRAL with its reason and no express line", () => {
    render(
      <SkewReadPanel
        read={{
          ...base,
          directional_lean: {
            lean: "NEUTRAL",
            confidence: "low",
            basis: "no proven separation for this bucket yet",
            express: "",
          },
        }}
      />,
    );
    expect(screen.getByText("NEUTRAL")).toBeTruthy();
    expect(screen.getByText(/no proven separation/)).toBeTruthy();
    expect(screen.queryByText(/express:/)).toBeNull();
  });
});
