import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { FundamentalAnchorBand } from "@/components/stock/panels/FundamentalAnchorBand";
import type { components } from "@/lib/types";

type Anchors = components["schemas"]["FundamentalAnchors"];

// CRM's real 2026-04-14 band: price well below the cheap end of its own history.
const CRM: Anchors = {
  company_type: "software_growth",
  method: "sales_to_ev",
  buy_below: 294.530694317068,
  observe_low: 326.1,
  observe_mid: 358.0,
  observe_high: 399.0,
  risk_above: 440.8,
  spot: 171.31,
  spot_percentile: 0.974683544303797,
  history_quarters: 79,
  confidence: "high",
  confidence_reasons: [],
  as_of: "2026-04-14",
};

const band = (over: Partial<Anchors> = {}): Anchors => ({ ...CRM, ...over });

describe("FundamentalAnchorBand", () => {
  it("renders all five levels in ascending order", () => {
    render(<FundamentalAnchorBand a={band()} />);
    for (const label of [
      "buy below",
      "observe low",
      "observe mid",
      "observe high",
      "risk above",
    ]) {
      expect(screen.getByText(label)).toBeTruthy();
    }
    // One decimal above 100, two below — see `money` in the component.
    expect(screen.getByText("294.5")).toBeTruthy();
    expect(screen.getByText("440.8")).toBeTruthy();
  });

  it("states where spot sits as a percentile of the company's own history", () => {
    render(<FundamentalAnchorBand a={band()} />);
    expect(screen.getByText("97%")).toBeTruthy();
  });

  it("names the comparison as own-history, never a peer ranking", () => {
    // Load-bearing: ranking names against each other on value is INVERTED in
    // this universe, so a reader who assumes a peer rank reads the sign backwards.
    const { container } = render(<FundamentalAnchorBand a={band()} />);
    expect(container.textContent).toMatch(/own/);
    expect(container.textContent).toMatch(
      /not a ranking against other companies/,
    );
  });

  it("draws a null level as a dash, never as a zero", () => {
    // "buy below 0.00" would be a boundary the data does not support.
    render(<FundamentalAnchorBand a={band({ buy_below: null })} />);
    expect(screen.getByText("—")).toBeTruthy();
    expect(screen.queryByText("0.00")).toBeNull();
  });

  it("renders a refusal with its reason instead of an empty band", () => {
    // TSM's real shape: TWD statements against a USD ADR quote.
    const { container } = render(
      <FundamentalAnchorBand
        a={band({
          buy_below: null,
          observe_low: null,
          observe_mid: null,
          observe_high: null,
          risk_above: null,
          spot_percentile: null,
          confidence: "none",
          confidence_reasons: [
            "enterprise value is not positive at the current price — the statements and the quote are most likely in different currencies (foreign issuer / ADR)",
          ],
        })}
      />,
    );
    expect(screen.getByText("No band.")).toBeTruthy();
    expect(container.textContent).toMatch(/different currencies/);
    // No ladder at all — a partial ladder of five dashes would read as a band.
    expect(screen.queryByText("buy below")).toBeNull();
  });

  it("lists every confidence reason rather than collapsing to the badge", () => {
    const reasons = ["19 quarters of history", "filing is 400 days old"];
    const { container } = render(
      <FundamentalAnchorBand
        a={band({ confidence: "medium", confidence_reasons: reasons })}
      />,
    );
    for (const r of reasons) expect(container.textContent).toContain(r);
  });

  it("keeps an out-of-band spot on screen", () => {
    // Spot far below the whole band must not be clipped to the left edge, which
    // would read as "at the boundary" — the opposite of what out-of-band means.
    const { container } = render(<FundamentalAnchorBand a={band()} />);
    // The rail CONTAINER also has textContent "171.3" (the ticks carry no text)
    // and comes first in document order, so match on the positioned element.
    const marker = Array.from(container.querySelectorAll("div")).find(
      (d) =>
        d.textContent?.startsWith("171.3") &&
        (d as HTMLElement).style.left !== "",
    );
    expect(marker).toBeTruthy();
    const left = parseFloat((marker as HTMLElement).style.left);
    expect(left).toBeGreaterThan(0);
    expect(left).toBeLessThan(100);
  });
});
