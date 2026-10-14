import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import {
  GoldAttributionSection,
  GoldBreakdownSection,
  GoldResearchConclusion,
} from "@/components/macro/goldFactor/GoldFactorBand";
import {
  GOLD_FACTOR as FIXTURE,
  GOLD_FLOWS as FLOWS,
} from "../fixtures/goldFactor";

function renderAll() {
  return render(
    <div>
      <GoldResearchConclusion data={FIXTURE} />
      <GoldBreakdownSection data={FIXTURE} flows={FLOWS} scope="s" />
      <GoldAttributionSection data={FIXTURE} />
    </div>,
  );
}

describe("gold factor sections", () => {
  it("renders every research panel, each carrying the research label", () => {
    renderAll();
    const ids = ["sensitivity", "explained", "breakdown", "ytd", "yearly", "slope-history", "drift", "regroup"];
    for (const id of ids) {
      const panel = document.getElementById(`gold-factor-${id}`);
      expect(panel, id).not.toBeNull();
      expect(within(panel!).getByText(/Describes the past, not a forecast · the direction test \(Phase 3\) failed/), id).toBeTruthy();
    }
    expect(screen.getByText(/below 0\.218 “explain little”, above 0\.402 “explain a lot”/)).toBeTruthy();
    expect(screen.getByText(/Now 26% \(explain some\)/)).toBeTruthy();
    expect(screen.getAllByText("interval crosses zero").length).toBe(2); // yield and haven, not the dollar
  });

  it("waterfall sums the window and ends at gold's own change", () => {
    renderAll();
    const panel = document.getElementById("gold-factor-breakdown")!;
    // 21 rows x 0.5 = +10.5 on the default window (1M); 5 rows x 0.5 = +2.5 for 1W
    expect(within(panel).getByText("+10.5")).toBeTruthy();
    fireEvent.click(within(panel).getByRole("button", { name: "1W" }));
    expect(within(panel).getByText("+2.5")).toBeTruthy();
  });

  it("yearly view defaults to 3 factors vs rest and switches to the five parts", () => {
    renderAll();
    const panel = document.getElementById("gold-factor-yearly")!;
    expect(within(panel).getByRole("button", { name: "3 factors vs rest" }).getAttribute("aria-pressed")).toBe("true");
    expect(within(panel).getByText("3 factors")).toBeTruthy();
    fireEvent.click(within(panel).getByRole("button", { name: "All 5" }));
    expect(within(panel).getByText("Unexplained")).toBeTruthy();
  });

  it("year table regroups without refitting: 3 factors + the rest = gold", () => {
    renderAll();
    const row = within(screen.getByTestId("gold-factor-year-table")).getByText("2025").closest("tr")!;
    const cells = [...row.querySelectorAll("td")].map((td) => td.textContent);
    // 2025: gold +40.0, sum 5+8+1 = +14.0, rest 20+6 = +26.0
    expect(cells).toEqual(["2025", "+40.0", "+5.0", "+8.0", "+1.0", "+14.0", "+20.0", "+6.0", "+26.0"]);
  });

  it("draws only flow series with history, never an empty chart", () => {
    renderAll();
    expect(within(document.getElementById("gold-flow-china")!).getByText(/latest 101\.5 t \(2026-03-31\)/)).toBeTruthy();
    expect(within(document.getElementById("gold-flow-cftc")!).getByText("No history stored for this series.")).toBeTruthy();
    expect(screen.getByText(/A reported reserve change is not a purchase/)).toBeTruthy();
  });
});
