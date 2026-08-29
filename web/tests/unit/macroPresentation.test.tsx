import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { DataDetails } from "@/components/macro/DataDetails";
import {
  BoardPanel,
  BoardSecTitle,
  BoardStatePill,
} from "@/components/macro/domain/BoardPanel";
import {
  basisLabel,
  fieldLabel,
  humanizeIdentifier,
  humanizeText,
  seriesLabel,
} from "@/components/macro/presentation";

describe("macro presentation vocabulary", () => {
  it("translates machine values without losing their meaning", () => {
    expect(humanizeIdentifier("WELL_ABOVE_TARGET")).toBe(
      "Well above target",
    );
    expect(humanizeIdentifier("ON_HOLD")).toBe("On hold");
    expect(humanizeIdentifier("RANGEBOUND")).toBe("Range-bound");
    expect(humanizeIdentifier("asset_mgr_net_pct_oi_change_4w")).toBe(
      "Asset managers · 4-week net share change",
    );
    expect(fieldLabel("confidence_reasons")).toBe("Confidence drivers");
    expect(humanizeText("usd cited policy_rates state")).toBe(
      "usd cited Policy & Rates state",
    );
  });

  it("uses market labels for known series and readable fallbacks", () => {
    expect(seriesLabel("DGS10")).toBe("10Y Treasury");
    expect(seriesLabel("DFII10")).toBe("10Y real yield");
    expect(seriesLabel("T10YIE")).toBe("10Y breakeven");
    expect(seriesLabel("custom_series_name")).toBe("Custom series name");
  });

  it("uses concise operator labels for inflation series and units", () => {
    expect(seriesLabel("PCEPILFE")).toBe("Core PCE");
    expect(seriesLabel("TRMMEANCPIM158SFRBCLE")).toBe("Trimmed-mean CPI");
    expect(seriesLabel("CORESTICKM159SFRBATL")).toBe("Sticky core CPI");
    expect(humanizeIdentifier("index_2017_100_sa")).toBe("2017=100 SA");
    expect(humanizeIdentifier("percent_change_annual_rate")).toBe(
      "Annualized",
    );
    expect(humanizeIdentifier("percent_change_from_year_ago")).toBe(
      "Year over year",
    );
  });

  it("renames provenance for an operator", () => {
    expect(basisLabel("REAL")).toBe("Live");
    expect(basisLabel("COMPUTED")).toBe("Derived");
    expect(basisLabel("PLANNED")).toBe("Planned");
    expect(basisLabel("REFERENCE")).toBe("Reference");
  });

  it("keeps source evidence in a closed data disclosure", () => {
    render(
      <DataDetails
        basis="COMPUTED"
        questions={["Q2", "Q7"]}
        sourceLabel="Formula"
        source="market_implied.path.points"
      />,
    );

    const details = screen.getByTestId("macro-data-details");
    expect(details.tagName).toBe("DETAILS");
    expect((details as HTMLDetailsElement).open).toBe(false);
    expect(screen.getByText("Data details")).toBeTruthy();
    expect(details.textContent).toContain("Derived");
    expect(details.textContent).toContain("market_implied.path.points");
    expect(details.getAttribute("data-questions")).toBe("Q2 Q7");
  });
});

describe("board presentation boundary", () => {
  it("keeps Q metadata without drawing Q chips", () => {
    const { container } = render(
      <>
        <BoardSecTitle title="Inflation" questions={["Q1", "Q7"]}>
          Current price pressure and what could change it.
        </BoardSecTitle>
        <BoardPanel
          id="sample"
          title="Price pressure"
          questions={["Q1", "Q7"]}
          basis="REAL"
          source="/api/macro/inflation"
        >
          <span>3.1%</span>
        </BoardPanel>
      </>,
    );

    expect(screen.getByRole("heading", { name: "Inflation" })).toHaveProperty(
      "parentElement.dataset.questions",
      "Q1 Q7",
    );
    const panel = screen.getByTestId("board-panel-sample");
    expect(panel.getAttribute("data-questions")).toBe("Q1 Q7");
    expect(container.querySelectorAll(".tag.q")).toHaveLength(0);
    expect(panel.querySelector("details")?.textContent).toContain("Live");
  });

  it("renders human state text and preserves the raw value as metadata", () => {
    render(
      <BoardStatePill
        facts={{
          state: "WELL_ABOVE_TARGET",
          direction: "RANGEBOUND",
          confidence: "0.75",
        }}
        testId="state"
      />,
    );
    const state = screen.getByTestId("state");
    expect(state.textContent).toBe(
      "Well above target · Range-bound · 75% confidence",
    );
    expect(state.getAttribute("data-raw-value")).toBe(
      "WELL_ABOVE_TARGET|RANGEBOUND",
    );
  });
});
