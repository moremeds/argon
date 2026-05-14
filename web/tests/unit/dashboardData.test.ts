import { describe, expect, it, vi } from "vitest";

import { loadDashboardData } from "@/lib/dashboardData";
import { api } from "@/lib/api";

vi.mock("@/lib/api", () => ({
  api: {
    watchlist: vi.fn(),
    ohlc: vi.fn(),
  },
}));

describe("loadDashboardData", () => {
  it("returns an empty dashboard when the API is still starting", async () => {
    vi.mocked(api.watchlist).mockRejectedValueOnce(new Error("ECONNREFUSED"));

    const result = await loadDashboardData(new URLSearchParams());

    expect(result.apiUnavailable).toBe(true);
    expect(result.data.tickers).toEqual([]);
    expect(result.sparklines).toEqual({});
  });
});
