import { describe, expect, it, vi } from "vitest";

import { loadDashboardData } from "@/lib/dashboardData";
import { api } from "@/lib/api";

vi.mock("@/lib/api", () => ({
  api: {
    watchlist: vi.fn(),
  },
}));

describe("loadDashboardData", () => {
  it("returns an empty dashboard when the API is still starting", async () => {
    vi.mocked(api.watchlist).mockRejectedValueOnce(new Error("ECONNREFUSED"));

    const result = await loadDashboardData(new URLSearchParams());

    expect(result.apiUnavailable).toBe(true);
    expect(result.data.tickers).toEqual([]);
  });

  it("returns the watchlist payload when the API succeeds", async () => {
    const payload = {
      scanned_at_min: null,
      scanned_at_max: null,
      scheduler_lag_seconds: null,
      queue: { total: 0, queued: 0, running: 0, oldest_requested_at: null },
      tickers: [],
    };
    vi.mocked(api.watchlist).mockResolvedValueOnce(payload);

    const result = await loadDashboardData(new URLSearchParams());

    expect(result.apiUnavailable).toBe(false);
    expect(result.data).toEqual(payload);
  });
});
