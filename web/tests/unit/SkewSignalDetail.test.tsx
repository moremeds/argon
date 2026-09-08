import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { SkewSignalDetail } from "@/components/stock/panels/SkewSignalDetail";
import type { SkewAnalysisResponse } from "@/lib/api";

// The panel was demoted from a directional forecast to a positioning descriptor
// (see docs/research/skew-directional/README.md). The fixture still carries a
// directional_lean block — the point of these tests is that the component now
// IGNORES it and renders no lean pill / validated badge / forward-return basis /
// suggested structure.
function makeData(
  over: Partial<SkewAnalysisResponse> = {},
): SkewAnalysisResponse {
  return {
    deviation_class: "RICH",
    rr_z_180d: "2.1",
    rr_pct_252d: "96",
    drive_class: "PANIC",
    regime: "HIGH_VOL",
    borrow_flag: "normal",
    read: {
      rho_confirms: true,
      earnings_gate: "pass",
      directional_lean: {
        lean: "BEARISH_TILT",
        confidence: "high",
        basis: "validated — RICH single_name bucket separated -4.5%/20d",
        express: "put-debit-spread — defined risk",
        structure_detail: {
          kind: "put_debit_spread",
          dte_target: 33,
          status: "ready",
          note: "defined risk",
          legs: [
            {
              action: "BUY",
              right: "PUT",
              strike: "95",
              actual_delta: "-0.26",
            },
            {
              action: "SELL",
              right: "PUT",
              strike: "88",
              actual_delta: "-0.13",
            },
          ],
        },
      },
      summary_bullets: [
        { label: "Shape — RICH put-skew", body: "Puts carry the richer wing." },
        {
          label: "Drive — PANIC",
          body: "Vol bid into weakness — downside fear.",
        },
        { label: "Spot–vol link — confirmed", body: "ρ confirms the read." },
        {
          label: "Relative value — fade/finance",
          body: "Skew is rich vs baseline: fade or finance the expensive wing.",
        },
      ],
    },
    ...over,
  } as unknown as SkewAnalysisResponse;
}

describe("SkewSignalDetail (descriptor)", () => {
  it("renders the four read rows with explanations and factual context", () => {
    render(<SkewSignalDetail data={makeData()} />);
    // Left rows: labels + values + explanation bodies.
    expect(screen.getByText("Deviation")).toBeTruthy();
    expect(screen.getByText("RICH")).toBeTruthy();
    expect(screen.getByText("Puts carry the richer wing.")).toBeTruthy();
    expect(screen.getByText("Drive")).toBeTruthy();
    expect(screen.getByText("FADE / FINANCE")).toBeTruthy();
    // Right card: factual context, not a forecast.
    expect(screen.getByText("Context")).toBeTruthy();
    expect(screen.getByText("borrow")).toBeTruthy();
    expect(screen.getByText("normal")).toBeTruthy();
  });

  it("shows NO directional forecast — no lean pill, validated badge, forward-return basis, or suggested structure", () => {
    render(<SkewSignalDetail data={makeData()} />);
    // The directional apparatus is gone even though the fixture supplies it.
    expect(screen.queryByTestId("skew-lean-pill")).toBeNull();
    expect(screen.queryByTestId("skew-lean-status")).toBeNull();
    expect(screen.queryByTestId("skew-lean-basis")).toBeNull();
    expect(screen.queryByTestId("skew-structure-detail")).toBeNull();
    // No BULLISH/BEARISH verdict word, no "validated" stamp, no forward-return %.
    expect(screen.queryByText("BEARISH")).toBeNull();
    expect(screen.queryByText("BULLISH")).toBeNull();
    expect(screen.queryByText("validated")).toBeNull();
    expect(screen.queryByText(/\/20d/)).toBeNull();
    expect(screen.queryByText(/confidence:/)).toBeNull();
  });

  it("still reflects the descriptor state: NOT CONFIRMED and NO EDGE for a normal, unconfirmed read", () => {
    render(
      <SkewSignalDetail
        data={makeData({
          deviation_class: "NORMAL",
          read: {
            rho_confirms: false,
            earnings_gate: "pass",
            directional_lean: {
              lean: "NEUTRAL",
              confidence: "low",
              basis: "no proven separation for this bucket yet",
              express: "",
            },
            summary_bullets: [],
          },
        } as unknown as Partial<SkewAnalysisResponse>)}
      />,
    );
    expect(screen.getByText("NOT CONFIRMED")).toBeTruthy();
    expect(screen.getByText("NO EDGE")).toBeTruthy();
  });
});
