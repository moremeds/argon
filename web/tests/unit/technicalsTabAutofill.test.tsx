import { render, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const noOhlcv = {
  ticker: "NVDA",
  backfill_status: "ready",
  as_of: "2026-07-09",
  header: {},
  series: [
    { as_of: "2026-07-08", close: 100 },
    { as_of: "2026-07-09", close: 101 },
  ],
  detail: {},
  forward_returns: [],
  vwap_anchor: null,
};
const withOhlcv = {
  ...noOhlcv,
  series: noOhlcv.series.map((r) => ({
    ...r,
    open: 99,
    high: 102,
    low: 98,
    volume: 5,
  })),
};

vi.mock("@/lib/api", () => ({
  api: {
    technicals: vi.fn(),
    technicalsLive: vi
      .fn()
      .mockResolvedValue({ ticker: "NVDA", available: false }),
    technicalsRefresh: vi.fn(),
  },
}));
// The chart needs a real canvas — stub it out; its logic is covered in Task 8 tests.
vi.mock("@/components/stock/panels/TechnicalsPriceChart", () => ({
  TechnicalsPriceChart: () => <div data-testid="price-chart" />,
}));

import { api } from "@/lib/api";
import { TechnicalsTab } from "@/components/stock/tabs/TechnicalsTab";

describe("TechnicalsTab auto-fill on open", () => {
  beforeEach(() => vi.clearAllMocks());

  it("fires the per-ticker refresh once when the latest row lacks OHLCV", async () => {
    vi.mocked(api.technicals).mockResolvedValue(noOhlcv as never);
    vi.mocked(api.technicalsRefresh).mockResolvedValue(withOhlcv as never);
    render(<TechnicalsTab ticker="NVDA" />);
    await waitFor(() => expect(api.technicalsRefresh).toHaveBeenCalledTimes(1));
    // never re-fires after the fresh (OHLCV-bearing) payload lands
    await waitFor(() => expect(api.technicalsRefresh).toHaveBeenCalledTimes(1));
  });

  it("does not fire when OHLCV is already present", async () => {
    vi.mocked(api.technicals).mockResolvedValue(withOhlcv as never);
    const { findByTestId } = render(<TechnicalsTab ticker="NVDA" />);
    await findByTestId("price-chart");
    expect(api.technicalsRefresh).not.toHaveBeenCalled();
  });
});
