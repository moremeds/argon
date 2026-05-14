import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
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
      scheduler_heartbeat_lag_seconds: 1,
      scheduler_heartbeat_name: "worker",
      rescan_heartbeat_lag_seconds: 8,
      watchlist_size: 97,
      source: "UnusualWhales",
      latency_p95_ms: 88,
      http_2xx: 120,
      http_4xx: 3,
      http_5xx: 1,
      uw_today: 40,
      cache_hit_pct: null,
    });

    render(<HealthPanel />);

    await waitFor(() => expect(screen.getByText("API")).toBeTruthy());
    expect(screen.getByText("Scheduler")).toBeTruthy();
    expect(screen.getByText("Rescan")).toBeTruthy();
    expect(screen.getAllByText("ONLINE").length).toBeGreaterThanOrEqual(2);
    expect(screen.getByText("STALE")).toBeTruthy();
    expect(screen.getByText("05/14 22:20 HKG")).toBeTruthy();
    expect(screen.queryByText("2026/05/14 22:20:42 HKG")).toBeNull();
    expect(screen.getByDisplayValue("UnusualWhales")).toBeTruthy();
    expect(screen.getByText("UnusualWhales")).toBeTruthy();
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
      scheduler_heartbeat_lag_seconds: null,
      scheduler_heartbeat_name: null,
      rescan_heartbeat_lag_seconds: null,
      watchlist_size: null,
      source: "UnusualWhales",
      latency_p95_ms: null,
      http_2xx: null,
      http_4xx: null,
      http_5xx: null,
      uw_today: null,
      cache_hit_pct: null,
    });

    render(<HealthPanel />);

    await waitFor(() => expect(screen.getAllByText("UNKNOWN").length).toBeGreaterThanOrEqual(2));
    expect(screen.getAllByText("—").length).toBeGreaterThanOrEqual(5);
  });

  it("reloads stats when provider source changes", async () => {
    vi.mocked(api.health)
      .mockResolvedValueOnce({
        ok: true,
        db: "up",
        scheduler_lag_seconds: 12,
        last_full_scan_at: "2026-05-14T14:20:42Z",
        reason: null,
        worker_lag_seconds: 1,
        scheduler_heartbeat_lag_seconds: 1,
        scheduler_heartbeat_name: "worker",
        rescan_heartbeat_lag_seconds: 1,
        watchlist_size: 97,
        source: "UnusualWhales",
        latency_p95_ms: 88,
        http_2xx: 120,
        http_4xx: 3,
        http_5xx: 1,
        uw_today: 40,
        cache_hit_pct: null,
      })
      .mockResolvedValueOnce({
        ok: true,
        db: "up",
        scheduler_lag_seconds: 12,
        last_full_scan_at: "2026-05-14T14:20:42Z",
        reason: null,
        worker_lag_seconds: 1,
        scheduler_heartbeat_lag_seconds: 1,
        scheduler_heartbeat_name: "worker",
        rescan_heartbeat_lag_seconds: 1,
        watchlist_size: 97,
        source: "Massive.com",
        latency_p95_ms: 55,
        http_2xx: 10,
        http_4xx: 0,
        http_5xx: 2,
        uw_today: null,
        cache_hit_pct: null,
      });

    render(<HealthPanel />);

    await waitFor(() => expect(api.health).toHaveBeenCalledWith("uw"));
    fireEvent.change(screen.getByRole("combobox", { name: "Source" }), {
      target: { value: "massive" },
    });

    await waitFor(() => expect(api.health).toHaveBeenCalledWith("massive"));
    expect(screen.getByText("Massive.com")).toBeTruthy();
    expect(screen.getByText("55ms")).toBeTruthy();
    expect(screen.getByText("10")).toBeTruthy();
    expect(screen.getByText("2")).toBeTruthy();
  });
});
