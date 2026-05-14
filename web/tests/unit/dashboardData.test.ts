import { describe, expect, it, vi } from "vitest";

import { loadDashboardData } from "@/lib/dashboardData";
import { api } from "@/lib/api";

vi.mock("@/lib/api", () => ({
  api: {
    watchlist: vi.fn(),
    ohlc: vi.fn(),
  },
}));

function watchlist(tickers: string[]) {
  return {
    scanned_at_min: null,
    scanned_at_max: null,
    scheduler_lag_seconds: null,
    tickers: tickers.map((ticker) => ({
      ticker,
      sector: "Technology",
      pinned: false,
      sort_rank: 0,
      spot: null,
      spot_quoted_at: null,
      spot_source: null,
      scanned_at: null,
      iv_atm: null,
      iv_rank: null,
      setup: { type: null, direction: null, score: null },
      aggression_pct: null,
      returns: { d1: null, w1: null, d30: null },
      gamma: {
        flip_distance: null,
        flip_price: null,
        per_1pct_move: null,
        max_strike: null,
        expiring_pct: null,
        expiring_date: null,
      },
      skew: { rr25d_30dte: null },
      positioning: {
        call_oi: null,
        put_oi: null,
        pcr_oi: null,
        pcr_vol: null,
        pcr_delta_30d: null,
      },
    })),
  };
}

describe("loadDashboardData", () => {
  it("returns an empty dashboard when the API is still starting", async () => {
    vi.mocked(api.watchlist).mockRejectedValueOnce(new Error("ECONNREFUSED"));

    const result = await loadDashboardData(new URLSearchParams());

    expect(result.apiUnavailable).toBe(true);
    expect(result.data.tickers).toEqual([]);
    expect(result.sparklines).toEqual({});
  });

  it("limits concurrent sparkline requests", async () => {
    vi.mocked(api.watchlist).mockResolvedValueOnce(
      watchlist(["A", "B", "C", "D"]),
    );
    let active = 0;
    let maxActive = 0;
    vi.mocked(api.ohlc).mockImplementation(async (ticker) => {
      active += 1;
      maxActive = Math.max(maxActive, active);
      await new Promise((resolve) => setTimeout(resolve, 1));
      active -= 1;
      return [
        {
          date: "2026-05-13",
          close: String(ticker.length),
          open: null,
          high: null,
          low: null,
          volume: null,
        },
      ];
    });

    const result = await loadDashboardData(new URLSearchParams(), 2);

    expect(result.apiUnavailable).toBe(false);
    expect(maxActive).toBeLessThanOrEqual(2);
    expect(Object.keys(result.sparklines)).toEqual(["A", "B", "C", "D"]);
  });
});
