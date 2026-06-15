import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { SkewSignalDetail } from "@/components/stock/panels/SkewSignalDetail";
import type { SkewAnalysisResponse } from "@/lib/api";

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

describe("SkewSignalDetail", () => {
  it("renders the lean pill, evidence, and the four read rows with explanations", () => {
    render(<SkewSignalDetail data={makeData()} />);
    // Lean surfaces both as the header pill and in the Evidence column.
    expect(screen.getAllByText("BEARISH").length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText(/confidence: high/)).toBeTruthy();
    expect(screen.getByText(/separated -4.5%\/20d/)).toBeTruthy();
    // Left rows: labels + values + explanation bodies.
    expect(screen.getByText("Deviation")).toBeTruthy();
    expect(screen.getByText("RICH")).toBeTruthy();
    expect(screen.getByText("Puts carry the richer wing.")).toBeTruthy();
    expect(screen.getByText("FADE / FINANCE")).toBeTruthy();
    // Evidence gate rows.
    expect(screen.getByText("express")).toBeTruthy();
    expect(screen.getByText("put-debit-spread — defined risk")).toBeTruthy();
  });

  it("shows NEUTRAL and NOT CONFIRMED when there is no edge", () => {
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
    expect(screen.getAllByText("NEUTRAL").length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText("NOT CONFIRMED")).toBeTruthy();
    expect(screen.getByText("NO EDGE")).toBeTruthy();
    // Empty express renders the em-dash placeholder.
    expect(screen.getByText("—")).toBeTruthy();
  });
});
