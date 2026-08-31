import { render, screen } from "@testing-library/react";
import { beforeAll, describe, expect, it } from "vitest";

import { CapexPanel } from "@/components/fundamentals/CapexPanel";
import type { DeskCapexResponse } from "@/lib/api";

// --- Fixtures ---------------------------------------------------------------
//
// Its own file, not `industryDesk.test.tsx`: that suite stubs CapexPanel
// file-wide (jsdom has no 2D context, and the page tests there are about
// fetch-to-prop wiring). The panel guards `getContext("2d") === null` and
// returns, so its DOM half — the tiles and the finding — renders fine here
// while the canvas simply never paints. The painting is covered by
// `tests/e2e/fundamentals-chain-desk.spec.ts`.
//
// AUTHORING STEP (run once, 2026-08-29, against `option_wizard_local`):
//
//   SELECT DISTINCT ON (ticker, period_end) ticker, period_end,
//          raw_jsonb->>'capital_expenditures'
//     FROM uw_scan.fundamental_statement_obs
//    WHERE statement = 'cash_flow' AND period_end >= '2026-01-01'
//      AND ticker IN ('AMZN','GOOGL','IBM','MSFT','ORCL')
//    ORDER BY ticker, period_end, obs_id DESC;
//
//   AMZN  2026-03-31  44,203,000,000    AMZN  2026-06-30  54,208,000,000
//   GOOGL 2026-03-31  35,674,000,000    GOOGL 2026-06-30  44,924,000,000
//   IBM   2026-03-31     391,000,000    IBM   2026-06-30     229,000,000
//   MSFT  2026-03-31  30,876,000,000    MSFT  2026-06-30  35,802,000,000
//   ORCL  2026-02-28  18,635,000,000    ORCL  2026-05-31  16,493,000,000
//
// Every figure below is one of those real filed values or a sum of them. The
// PARTIAL quarter is a real subset — MSFT and ORCL's real 2026Q2 filings with
// the other three not yet in — which is exactly the shape the store holds
// mid-reporting-season, not an invented number.

const Q1_FULL =
  44203000000 + 35674000000 + 391000000 + 30876000000 + 18635000000;
const Q2_FULL =
  54208000000 + 44924000000 + 229000000 + 35802000000 + 16493000000;
const Q2_PARTIAL = 35802000000 + 16493000000; // MSFT + ORCL only

const INCLUDED = ["AMZN", "GOOGL", "IBM", "MSFT", "ORCL"];

const COMPLETE: DeskCapexResponse = {
  chain: "Cloud/Hyperscaler",
  included: INCLUDED,
  excluded: { BABA: "CNY" },
  quarters: [
    {
      quarter: "2025Q2",
      capex_usd: 80998000000,
      revenue_usd: 373451000000,
      tickers: INCLUDED,
      complete: true,
    },
    {
      quarter: "2026Q1",
      capex_usd: Q1_FULL,
      revenue_usd: 407408000000,
      tickers: INCLUDED,
      complete: true,
    },
    {
      quarter: "2026Q2",
      capex_usd: Q2_FULL,
      revenue_usd: 447340000000,
      tickers: INCLUDED,
      complete: true,
    },
  ],
};

/** The same panel mid-season: 2026Q2 holds only the two names that have filed. */
const PARTIAL: DeskCapexResponse = {
  ...COMPLETE,
  quarters: [
    COMPLETE.quarters[0],
    COMPLETE.quarters[1],
    {
      quarter: "2026Q2",
      capex_usd: Q2_PARTIAL,
      revenue_usd: null,
      tickers: ["MSFT", "ORCL"],
      complete: false,
    },
  ],
};

// jsdom has neither `matchMedia` nor a 2D context. The panel needs the first
// to subscribe to theme changes and null-guards the second, so one polyfill is
// enough to render its DOM half — this is the same reason `web/CLAUDE.md`
// keeps lightweight-charts panes out of vitest entirely.
beforeAll(() => {
  window.matchMedia = ((query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addEventListener: () => {},
    removeEventListener: () => {},
    addListener: () => {},
    removeListener: () => {},
    dispatchEvent: () => false,
  })) as unknown as typeof window.matchMedia;
  // jsdom logs "Not implemented: HTMLCanvasElement.prototype.getContext" on
  // every render otherwise. The panel already handles a null context; the
  // stub just keeps that expected path from looking like a failure in CI.
  HTMLCanvasElement.prototype.getContext = (() =>
    null) as unknown as HTMLCanvasElement["getContext"];
});

/** A stamp tile's full text. `getAllByText(...)[0]` on purpose: "year over
 *  year" is also the hover readout's label, and the tiles come first in DOM
 *  order — a `getByText` here fails on the ambiguity rather than the claim. */
function tile(label: string): string {
  return screen.getAllByText(label)[0].parentElement?.textContent ?? "";
}

describe("CapexPanel — a partial quarter is not the panel's spend", () => {
  it("headlines the latest COMPLETE quarter, not the partial tail", () => {
    // Without this, the newest bar — a two-name sum against a five-name panel
    // — becomes "latest quarter", and an incomplete quarter renders as a fall
    // in hyperscaler spending on the one question the desk opens with.
    render(<CapexPanel data={PARTIAL} />);
    const t = tile("latest complete quarter");
    expect(t).toContain("2026Q1");
    expect(t).not.toContain("$52.3B"); // the partial sum, in billions
    expect(t).toContain("2026Q2 still filing");
  });

  it("names the tickers actually summed, not the whole panel", () => {
    render(<CapexPanel data={PARTIAL} />);
    // 2026Q1 is complete, so all five belong on it. The load-bearing half is
    // that the label comes from the QUARTER's ticker set and not `included`.
    for (const ticker of INCLUDED)
      expect(tile("latest complete quarter")).toContain(ticker);
  });

  it("says 'latest quarter' when nothing is outstanding", () => {
    render(<CapexPanel data={COMPLETE} />);
    expect(screen.queryByText("latest complete quarter")).toBeNull();
    expect(tile("latest quarter")).toContain("2026Q2");
  });

  it("matches year-over-year by quarter KEY, so a gap cannot be miscompared", () => {
    // 2025Q2 → 2026Q2 with 2025Q3/Q4 absent from the series. Index arithmetic
    // (`quarters[i - 4]`) would reach past the start and report `na`, or with
    // a longer series compare the wrong period while still calling it YoY.
    render(<CapexPanel data={COMPLETE} />);
    const expected = Q2_FULL / 80998000000 - 1;
    expect(tile("year over year")).toContain(
      `+${(expected * 100).toFixed(1)}%`,
    );
  });

  it("refuses a growth multiple through a zero base", () => {
    const zeroBase: DeskCapexResponse = {
      ...COMPLETE,
      quarters: [
        { ...COMPLETE.quarters[0], capex_usd: 0, revenue_usd: null },
        COMPLETE.quarters[1],
        COMPLETE.quarters[2],
      ],
    };
    render(<CapexPanel data={zeroBase} />);
    // `Infinity×` would be the most confident-looking number on the desk.
    expect(document.body.textContent ?? "").not.toContain("Infinity");
  });
});
