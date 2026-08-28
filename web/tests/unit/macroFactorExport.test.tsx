import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import {
  DeliveryFormPanel,
  ExportRefusalPanel,
  FactorVectorPanel,
  type FactorExportSlots,
} from "@/components/macro/domain/FactorExport";
import type { MacroDomainState } from "@/components/macro/types";
import FIXTURE from "../fixtures/macroDomainStates.json";

/**
 * Board tab 07 — Factor Export.
 *
 * The tab's entire claim is that it ADDS NOTHING: it flattens four domain states that
 * other tabs already publish. So the tests are about the flattening and about what the
 * page says when part of it is missing — not about any number, because there is no number
 * here that this tab computed.
 */
const D = FIXTURE.domains as unknown as Record<string, MacroDomainState>;

const ALL: FactorExportSlots = {
  inflation: { value: D.inflation },
  rates: { value: D.rates },
  usd: { value: D.usd },
  gold: { value: D.gold },
};

const EXPECTED_ROWS =
  (D.inflation.factors?.length ?? 0) +
  (D.rates.factors?.length ?? 0) +
  (D.usd.factors?.length ?? 0) +
  (D.gold.factors?.length ?? 0);

describe("macro factor vector", () => {
  it("carries every factor of every domain, and nothing else", () => {
    render(<FactorVectorPanel slots={ALL} />);
    const body = within(screen.getByTestId("factor-vector-table")).getAllByRole(
      "row",
    );
    // header + every domain factor + the one labels row the board ends on.
    expect(body).toHaveLength(1 + EXPECTED_ROWS + 1);
  });

  it("marks the four state labels as context, never as an exportable factor", () => {
    // The measured reason, from the board: labels chatter (inflation flipped 4x in 68
    // months), so an equity backtest joining one gets boundary noise. The row exists to
    // be refused; if it ever renders a value it has become the thing it warns about.
    render(<FactorVectorPanel slots={ALL} />);
    const row = screen.getByText("state labels ×4").closest("tr");
    expect(row).not.toBeNull();
    expect(row?.textContent).toContain("labels · context only");
    expect(row?.textContent).toContain("see each domain tab");
  });

  it("names a domain that did not answer instead of silently shortening", () => {
    // A consumer joining this table cannot tell a factor that is ABSENT from one that was
    // never asked for. The page has to make that difference visible or the export is
    // quietly wrong in a way nothing downstream can detect.
    render(<FactorVectorPanel slots={{ inflation: { value: D.inflation } }} />);
    const read = screen.getByTestId("factor-vector-read");
    expect(read.textContent).toContain("3 of 4 domains did not answer");
    expect(read.textContent).toContain("rates");
    expect(read.textContent).toContain("usd");
    expect(read.textContent).toContain("gold");
  });

  it("says there is no vector rather than rendering an empty table", () => {
    render(<FactorVectorPanel slots={{}} />);
    expect(screen.queryByTestId("factor-vector-table")).toBeNull();
    expect(screen.getByTestId("factor-vector-empty").textContent).toContain(
      "statement about the engines",
    );
  });

  it("prints the availability instant, which is what makes the export point-in-time", () => {
    // `period_end` is what a number is ABOUT; `available_at` is when the desk could first
    // have known it. A backtest that joins on the first crosses its own information
    // boundary, so the availability instant is the one that reaches the column.
    render(<FactorVectorPanel slots={ALL} />);
    const first = (D.inflation.factors ?? [])[0];
    const at = first.available_at.slice(0, 10);
    const row = screen.getByText(first.series_id).closest("tr");
    expect(row?.textContent).toContain(at);
  });
});

describe("the export's own boundaries", () => {
  it("keeps the delivery form PLANNED, with nothing callable on it", () => {
    render(<DeliveryFormPanel />);
    const panel = screen.getByTestId("board-panel-factor-delivery");
    expect(panel.getAttribute("data-basis")).toBe("PLANNED");
    // No route may be presented as though it answers today — that is the whole reason
    // the basis vocabulary has a PLANNED value.
    expect(panel.textContent).toContain("nothing on this panel is callable");
  });

  it("refuses any forward-return claim, in the panel the board gives it", () => {
    render(<ExportRefusalPanel />);
    expect(screen.getByTestId("factor-export-refusal").textContent).toContain(
      "NO PREDICTIVE CLAIM",
    );
    expect(
      screen
        .getByTestId("board-panel-factor-refusal")
        .getAttribute("data-questions"),
    ).toBe("Q7");
  });
});
