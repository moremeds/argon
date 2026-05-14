import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { HealthPanel } from "@/components/shared/HealthPanel";
import { api } from "@/lib/api";

vi.mock("@/lib/api", () => ({
  api: {
    health: vi.fn(),
  },
}));

describe("HealthPanel", () => {
  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  it("renders provider usage stats from health", async () => {
    vi.mocked(api.health).mockResolvedValue({
      ok: true,
      db: "up",
      scheduler_lag_seconds: 12,
      last_full_scan_at: "2026-05-14T14:20:42Z",
      reason: null,
      worker_lag_seconds: 1,
      watchlist_size: 97,
      source: "massive.com",
      latency_p95_ms: 88,
      http_2xx: 120,
      http_4xx: 3,
      http_5xx: 1,
      uw_today: 40,
      cache_hit_pct: null,
    });

    render(<HealthPanel />);

    await waitFor(() => expect(screen.getByText("ONLINE")).toBeTruthy());
    expect(screen.getByText("88ms")).toBeTruthy();
    expect(screen.getByText("120")).toBeTruthy();
    expect(screen.getByText("3")).toBeTruthy();
    expect(screen.getByText("1")).toBeTruthy();
  });

  it("keeps dashes for missing metrics", async () => {
    vi.mocked(api.health).mockResolvedValue({
      ok: false,
      db: "up",
      scheduler_lag_seconds: null,
      last_full_scan_at: null,
      reason: "no successful full scan yet",
      worker_lag_seconds: null,
      watchlist_size: null,
      source: "massive.com",
      latency_p95_ms: null,
      http_2xx: null,
      http_4xx: null,
      http_5xx: null,
      uw_today: null,
      cache_hit_pct: null,
    });

    render(<HealthPanel />);

    await waitFor(() => expect(screen.getByText("UNKNOWN")).toBeTruthy());
    expect(screen.getAllByText("—").length).toBeGreaterThanOrEqual(5);
  });
});
