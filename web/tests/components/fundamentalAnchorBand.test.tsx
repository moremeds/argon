import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import {
  FundamentalAnchorBand,
  rankPhrase,
} from "@/components/stock/panels/FundamentalAnchorBand";
import type { components } from "@/lib/types";

type Anchors = components["schemas"]["FundamentalAnchors"];

// CRM's real 2026-04-14 band, recomputed on the shipped trailing 20-quarter
// window: price well below the cheap end of its own recent history, and
// `spot_percentile` saturated at exactly 1 — the case the rank phrasing exists
// for. Frozen from uw_scan.valuation_anchors.
const CRM: Anchors = {
  company_type: "software_growth",
  method: "sales_to_ev",
  buy_below: 255.396869307571,
  observe_low: 264.047995765103,
  observe_mid: 291.056449482469,
  observe_high: 312.652629377653,
  risk_above: 349.050331820539,
  spot: 171.31,
  spot_percentile: 1,
  history_quarters: 20,
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
    expect(screen.getByText("255.4")).toBeTruthy();
    expect(screen.getByText("349.1")).toBeTruthy();
  });

  it("states where spot sits as a RANK, naming the sample it is a rank of", () => {
    // Not "cheaper than 100%". The percentile is a count over 20 observations,
    // so it can only take 21 values and every step is 5 points — a percentage
    // implies a precision the sample cannot carry, and at the top it printed a
    // bound rather than the fact that spot is at or past the cheapest reading.
    render(<FundamentalAnchorBand a={band()} />);
    expect(
      screen.getByText("Cheaper than any of its last 20 quarters"),
    ).toBeTruthy();
  });

  it("phrases the interior and both ends of the rank", () => {
    expect(rankPhrase(0.8, 20)).toBe("Cheaper than 16 of its last 20 quarters");
    expect(rankPhrase(1, 20)).toBe("Cheaper than any of its last 20 quarters");
    expect(rankPhrase(0, 20)).toBe("Richer than any of its last 20 quarters");
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
