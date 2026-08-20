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

  it("omits a null level entirely, never drawing it as a zero", () => {
    // "buy below 0.00" would be a boundary the data does not support. The level
    // is now simply absent from the axis rather than shown as a dash in a
    // separate table — that table was removed, see the alignment test below.
    render(<FundamentalAnchorBand a={band({ buy_below: null })} />);
    expect(screen.queryByText("0.00")).toBeNull();
    expect(screen.queryByText("255.4")).toBeNull();
    expect(screen.queryByText("buy below")).toBeNull();
    // The remaining four still render.
    expect(screen.getByText("349.1")).toBeTruthy();
  });

  it("places every label at the same position as its own tick", () => {
    // THE regression test. The rail placed ticks by value while the labels below
    // were an evenly-spaced five-column grid, so on all 233 live bands the two
    // disagreed — median 20, max 80 percentage points of panel width. AAPL
    // printed "buy below 247.1" under a spot the rail read as ~253.
    //
    // Asserting label-left == tick-left is what makes the axis an axis; a test
    // that only checked "the number appears somewhere" passed throughout the bug.
    const { container } = render(<FundamentalAnchorBand a={band()} />);
    const positioned = Array.from(container.querySelectorAll("div")).filter(
      (d) => (d as HTMLElement).style.left !== "",
    ) as HTMLElement[];

    for (const [, label] of [
      ["buy_below", "buy below"],
      ["observe_low", "observe low"],
      ["observe_mid", "observe mid"],
      ["observe_high", "observe high"],
      ["risk_above", "risk above"],
    ] as const) {
      const text = positioned.find((d) => d.textContent?.endsWith(label));
      expect(text, `label block for ${label}`).toBeTruthy();
      // Its tick carries the identical left; find a zero-text sibling matching it.
      const tick = positioned.find(
        (d) => d.textContent === "" && d.style.left === text!.style.left,
      );
      expect(
        tick,
        `tick aligned with ${label} at ${text!.style.left}`,
      ).toBeTruthy();
    }
  });

  it("spaces labels by value, not evenly — the gaps carry the information", () => {
    // CRM's levels bunch: 255.4 / 264.0 / 291.1 / 312.7 / 349.1. An even layout
    // would put them at 10/30/50/70/90% and imply a uniform spread the data does
    // not have. buy_below and observe_low are 8.7 apart out of a 178-wide rail
    // span (spot 171.3 sets the low end), so they must sit close together.
    const { container } = render(<FundamentalAnchorBand a={band()} />);
    const lefts = (
      Array.from(container.querySelectorAll("div")) as HTMLElement[]
    )
      .filter((d) => d.style.left !== "" && d.textContent !== "")
      .map((d) => parseFloat(d.style.left))
      .sort((x, y) => x - y);
    const gaps = lefts.slice(1).map((v, i) => v - lefts[i]);
    expect(Math.min(...gaps)).toBeLessThan(10);
    expect(Math.max(...gaps)).toBeGreaterThan(15);
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

  it("leads a refusal with the reason, not with how to read a band", () => {
    // NVDA's real 2026-08-14 refusal. The explainer paragraph teaches how to
    // read five levels and a spot marker, none of which are on screen here, and
    // it sat ABOVE the one sentence that answers "where is the band?".
    const { container } = render(
      <FundamentalAnchorBand
        a={band({
          company_type: "platform_scale",
          method: "fcf_yield",
          buy_below: null,
          observe_low: null,
          observe_mid: null,
          observe_high: null,
          risk_above: null,
          spot: 225.16,
          spot_percentile: null,
          confidence: "none",
          confidence_reasons: [
            "own 20-quarter valuation range spans 17.4x, wider than the 4x limit: leaning one way rather than swinging (rho +0.68) — the window covers two valuation regimes, not one, because the fundamental outgrew the price through it",
          ],
        })}
      />,
    );
    const text = container.textContent ?? "";
    expect(text).toMatch(/spans 17\.4x/);
    // The explainer is gone, not merely reordered: on a refusal it describes a
    // drawing that does not exist.
    expect(text).not.toMatch(/percentiles of its/);
    // And the header still reports the window the refusal was taken on, which
    // is the other half of the same bug — "0q" read as "nothing ingested".
    expect(text).toMatch(/20q/);
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

  it("renders a methodless refusal without a dangling separator", () => {
    // JPM's real shape after the 2026-08-19 routing fix. `financials` carries NO
    // method: the refusal is that none applies, because every yield here is
    // denominated in enterprise value and for a deposit-funded balance sheet
    // that is not a meaningful denominator. The header used to interpolate the
    // method unconditionally, so a null printed as "financials ·  · 20q" — an
    // empty segment that reads as a missing value rather than an absent concept.
    const { container } = render(
      <FundamentalAnchorBand
        a={band({
          company_type: "financials",
          method: null,
          buy_below: null,
          observe_low: null,
          observe_mid: null,
          observe_high: null,
          risk_above: null,
          spot: 360.96,
          spot_percentile: null,
          confidence: "none",
          confidence_reasons: [
            "no valuation band for a deposit-funded balance sheet: every method " +
              "here prices a company through its enterprise value, and for a " +
              "bank, broker or lender the funding is the business rather than a " +
              "claim against it, so enterprise value is not a meaningful " +
              "denominator",
          ],
        })}
      />,
    );
    const text = container.textContent ?? "";
    expect(text).toMatch(/financials/);
    expect(text).toMatch(/funding is the business/);
    // The type is followed straight by the window — no empty method segment.
    expect(text).toMatch(/financials · 20q/);
    expect(text).not.toMatch(/· +·/);
    expect(screen.getByText("No band.")).toBeTruthy();
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
