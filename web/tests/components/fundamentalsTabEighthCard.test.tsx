import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

const CARD = {
  ticker: "NVDA",
  composite: 0.42,
  composite_series: [],
  composite_percentile: null,
  series_dates: ["2026-04-30"],
  panel_size: 233,
  subscores: [
    {
      feature: "gross_margin",
      value: 0.7493,
      unit: "ratio",
      direction: null,
      suppressed_by: [],
      series: [0.7493],
      percentile: { percentile: 0.9, n: 233 },
    },
  ],
  anchors: null,
  coverage: {
    features_present: 1,
    features_total: 7,
    missing: [],
    suppressed: [],
  },
  provenance: {
    engine_version: "e1",
    inputs_hash: "abc123",
    as_of: "2026-04-30",
    period_end: "2026-04-30",
    knowledge_date: "2026-06-14",
    filing_date_known: true,
    source_obs_count: 3,
  },
};

const STATEMENTS = {
  ticker: "NVDA",
  period_ends: ["2026-01-31", "2026-04-30"],
  reported_currency: "USD",
  features: [
    {
      feature: "revenue_earnings",
      basis: "ttm",
      unit: "currency",
      series: [
        {
          key: "total_revenue_ttm",
          label: "revenue TTM",
          role: "input",
          unit: "currency",
          values: [220000000000, 253491000000],
        },
        {
          key: "net_income_ttm",
          label: "net income TTM",
          role: "input",
          unit: "currency",
          values: [130000000000, 159613000000],
        },
        {
          key: "fcf_ttm",
          label: "free cash flow TTM",
          role: "input",
          unit: "currency",
          values: [110000000000, 115200000000],
        },
      ],
      ratio: [null, null],
    },
  ],
};

vi.mock("@/lib/api", () => ({
  api: {
    fundamentals: vi.fn(() => Promise.resolve(CARD)),
    fundamentalStatements: vi.fn(() => Promise.resolve(STATEMENTS)),
  },
}));

import { FundamentalsTab } from "@/components/stock/tabs/FundamentalsTab";

describe("the eighth card", () => {
  it("renders alongside the subscores", async () => {
    render(<FundamentalsTab ticker="NVDA" />);
    expect(await screen.findByTestId("subscore-revenue_earnings")).toBeTruthy();
  });

  it("says it is not scored, and shows no percentile", async () => {
    // The seven around it are members of a validated set. A tile that looked
    // identical would be read as an eighth measured feature, which the
    // composite's verdicts do not cover.
    render(<FundamentalsTab ticker="NVDA" />);
    const tile = await screen.findByTestId("subscore-revenue_earnings");
    expect(tile.textContent).toMatch(/not scored/i);
    expect(tile.textContent).not.toMatch(/of 233/);
  });

  it("shows all three TTM figures, not just revenue", async () => {
    // Design §2 names revenue, net income and free cash flow. Revenue alone
    // makes the card a decoration rather than the summary it is meant to be.
    render(<FundamentalsTab ticker="NVDA" />);
    const tile = await screen.findByTestId("subscore-revenue_earnings");
    expect(tile.textContent).toMatch(/\$253\.5B/); // revenue TTM
    expect(tile.textContent).toMatch(/net income \$159\.6B/);
    expect(tile.textContent).toMatch(/FCF \$115\.2B/);
  });

  it("draws the mini series", async () => {
    render(<FundamentalsTab ticker="NVDA" />);
    const tile = await screen.findByTestId("subscore-revenue_earnings");
    expect(tile.querySelector("svg")).toBeTruthy();
  });
});
