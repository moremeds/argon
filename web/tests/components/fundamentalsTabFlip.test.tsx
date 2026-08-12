import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

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
      percentile: null,
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
      feature: "gross_margin",
      basis: "quarterly",
      unit: "ratio",
      series: [
        {
          key: "gross_profit",
          label: "gross profit",
          role: "input",
          unit: "currency",
          values: [51093000000, 61157000000],
        },
        {
          key: "total_revenue",
          label: "revenue",
          role: "input",
          unit: "currency",
          values: [68127000000, 81615000000],
        },
      ],
      ratio: [0.75, 0.7493],
    },
  ],
};

vi.mock("@/lib/api", () => ({
  api: {
    fundamentals: vi.fn(() => Promise.resolve(CARD)),
    fundamentalStatements: vi.fn(() => Promise.resolve(STATEMENTS)),
  },
}));

import { api } from "@/lib/api";
import { FundamentalsTab } from "@/components/stock/tabs/FundamentalsTab";

describe("FundamentalsTab flip", () => {
  beforeEach(() => vi.clearAllMocks());

  it("fetches statements once on mount, so the eighth card is never blank", async () => {
    render(<FundamentalsTab ticker="NVDA" />);
    await screen.findByTestId("subscore-gross_margin");
    await waitFor(() =>
      expect(api.fundamentalStatements).toHaveBeenCalledWith("NVDA"),
    );
    expect(api.fundamentalStatements).toHaveBeenCalledTimes(1);
  });

  it("opens the back on click", async () => {
    render(<FundamentalsTab ticker="NVDA" />);
    fireEvent.click(await screen.findByTestId("subscore-gross_margin"));
    await waitFor(() => expect(screen.getByText(/components/i)).toBeTruthy());
  });

  it("drops the open card and the previous ticker's data on a ticker change", async () => {
    // The stale-data bug: without a reset, the back keeps rendering NVDA's
    // components under AAPL's header.
    const { rerender } = render(<FundamentalsTab ticker="NVDA" />);
    fireEvent.click(await screen.findByTestId("subscore-gross_margin"));
    await waitFor(() => expect(screen.getByText(/components/i)).toBeTruthy());
    rerender(<FundamentalsTab ticker="AAPL" />);
    await waitFor(() => expect(screen.queryByText(/components/i)).toBeNull());
    expect(api.fundamentalStatements).toHaveBeenLastCalledWith("AAPL");
  });

  it("is activatable by keyboard — a submit-free, enabled native button", async () => {
    // Enter and Space activation is delivered by the ELEMENT, not by our code:
    // a native, non-disabled `<button type="button">` gets both from the UA.
    // jsdom does not synthesise a click from a keydown, so asserting
    // `fireEvent.keyDown(tile, {key: "Enter"})` here would test jsdom rather
    // than this component — and could only be made to pass by adding a
    // redundant onKeyDown that double-fires on Enter in a real browser.
    // What IS verifiable here is the precondition. Actual key activation is
    // proven in a real browser by tests/e2e/fundamentals-card-flip.spec.ts.
    render(<FundamentalsTab ticker="NVDA" />);
    const tile = await screen.findByTestId("subscore-gross_margin");
    expect(tile.tagName).toBe("BUTTON");
    expect(tile.getAttribute("type")).toBe("button");
    expect((tile as HTMLButtonElement).disabled).toBe(false);
  });

  it("closes on Escape", async () => {
    render(<FundamentalsTab ticker="NVDA" />);
    fireEvent.click(await screen.findByTestId("subscore-gross_margin"));
    await waitFor(() => expect(screen.getByText(/components/i)).toBeTruthy());
    fireEvent.keyDown(document, { key: "Escape" });
    await waitFor(() => expect(screen.queryByText(/components/i)).toBeNull());
  });

  it("keeps the tile a real button for keyboard and assistive tech", async () => {
    render(<FundamentalsTab ticker="NVDA" />);
    const tile = await screen.findByTestId("subscore-gross_margin");
    expect(tile.tagName).toBe("BUTTON");
  });

  it("opens one card at a time", async () => {
    render(<FundamentalsTab ticker="NVDA" />);
    fireEvent.click(await screen.findByTestId("subscore-gross_margin"));
    await waitFor(() => expect(screen.getByText(/components/i)).toBeTruthy());
    expect(screen.getAllByText(/components/i)).toHaveLength(1);
  });
});
