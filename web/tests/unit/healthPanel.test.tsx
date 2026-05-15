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
      spot_refresh_heartbeat_lag_seconds: 240,
      spot_quote_lag_seconds: 60,
      latest_spot_quote_at: "2026-05-14T14:19:42Z",
      latest_spot_quote_fetched_at: "2026-05-14T14:20:42Z",
      watchlist_size: 97,
      source: "UnusualWhales",
      latency_p95_ms: 88,
      http_2xx: 120,
      http_4xx: 3,
      http_5xx: 1,
      uw_today: 40,
      cache_hit_pct: null,
      throughput_window_minutes: 15,
      requests_per_minute: 12.4,
      http_429: 2,
      avg_scan_duration_seconds: 125,
      queue_drain_rate_per_minute: 1.6,
      record_health_ok: true,
      record_health: [],
      workers: [
        {
          label: "UW 1",
          role: "uw",
          index: 0,
          heartbeat_name: "worker:uw:0",
          lag_seconds: 1,
          last_beat_at: "2026-05-14T14:20:41Z",
        },
        {
          label: "UW 2",
          role: "uw",
          index: 1,
          heartbeat_name: "worker:uw:1",
          lag_seconds: null,
          last_beat_at: null,
        },
        {
          label: "Massive 1",
          role: "massive",
          index: 0,
          heartbeat_name: "worker:massive:0",
          lag_seconds: 240,
          last_beat_at: "2026-05-14T14:16:42Z",
        },
        {
          label: "Massive 2",
          role: "massive",
          index: 1,
          heartbeat_name: "worker:massive:1",
          lag_seconds: 700,
          last_beat_at: "2026-05-14T14:09:02Z",
        },
      ],
    });

    render(<HealthPanel />);

    await waitFor(() => expect(screen.getByText("API")).toBeTruthy());
    expect(screen.getByText("Scheduler")).toBeTruthy();
    expect(screen.getByText("UW Workers")).toBeTruthy();
    expect(screen.getByText("Massive Workers")).toBeTruthy();
    expect(screen.queryByText("UW 1")).toBeNull();
    expect(screen.queryByText("Massive 1")).toBeNull();
    expect(screen.queryByText("UW Worker")).toBeNull();
    expect(screen.getByText("Query Coverage")).toBeTruthy();
    expect(screen.getByText("OK")).toBeTruthy();
    expect(screen.getByText("Last spot")).toBeTruthy();
    expect(screen.getAllByText("1m").length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText("ONLINE").length).toBeGreaterThanOrEqual(2);
    expect(screen.getAllByText("1/2")).toHaveLength(2);
    expect(screen.getByText("05/14 22:20 HKG")).toBeTruthy();
    expect(screen.queryByText("2026/05/14 22:20:42 HKG")).toBeNull();
    expect(screen.getByDisplayValue("UnusualWhales")).toBeTruthy();
    expect(screen.getByText("UnusualWhales")).toBeTruthy();
    expect(screen.queryByText("Cache Hit")).toBeNull();
    expect(screen.getByText("Req avg/min")).toBeTruthy();
    expect(screen.getByText("Queue avg/min")).toBeTruthy();
    expect(screen.getByText("88ms")).toBeTruthy();
    expect(screen.getByText("12.4/m")).toBeTruthy();
    expect(screen.getByText("2")).toBeTruthy();
    expect(screen.getByText("2m")).toBeTruthy();
    expect(screen.getByText("1.6/m")).toBeTruthy();
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
      spot_refresh_heartbeat_lag_seconds: null,
      spot_quote_lag_seconds: null,
      latest_spot_quote_at: null,
      latest_spot_quote_fetched_at: null,
      watchlist_size: null,
      source: "UnusualWhales",
      latency_p95_ms: null,
      http_2xx: null,
      http_4xx: null,
      http_5xx: null,
      uw_today: null,
      cache_hit_pct: null,
      throughput_window_minutes: 15,
      record_health_ok: null,
      record_health: [],
      workers: [],
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
        spot_refresh_heartbeat_lag_seconds: 1,
        spot_quote_lag_seconds: 60,
        latest_spot_quote_at: "2026-05-14T14:19:42Z",
        latest_spot_quote_fetched_at: "2026-05-14T14:20:42Z",
        watchlist_size: 97,
        source: "UnusualWhales",
        latency_p95_ms: 88,
        http_2xx: 120,
        http_4xx: 3,
        http_5xx: 1,
        uw_today: 40,
        cache_hit_pct: null,
        throughput_window_minutes: 15,
        record_health_ok: true,
        record_health: [],
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
        spot_refresh_heartbeat_lag_seconds: 1,
        spot_quote_lag_seconds: 60,
        latest_spot_quote_at: "2026-05-14T14:19:42Z",
        latest_spot_quote_fetched_at: "2026-05-14T14:20:42Z",
        watchlist_size: 97,
        source: "Massive.com",
        latency_p95_ms: 55,
        http_2xx: 10,
        http_4xx: 0,
        http_5xx: 2,
        uw_today: null,
        cache_hit_pct: null,
        throughput_window_minutes: 15,
        record_health_ok: true,
        record_health: [],
      });

    render(<HealthPanel />);

    await waitFor(() =>
      expect(api.health).toHaveBeenCalledWith("uw", {
        recordMinCoverage: 0.9,
        recordWindowHours: 8,
      }),
    );
    fireEvent.change(screen.getByRole("combobox", { name: "Source" }), {
      target: { value: "massive" },
    });

    await waitFor(() =>
      expect(api.health).toHaveBeenCalledWith("massive", {
        recordMinCoverage: 0.9,
        recordWindowHours: 8,
      }),
    );
    expect(screen.getByText("Massive.com")).toBeTruthy();
    expect(screen.getByText("55ms")).toBeTruthy();
    expect(screen.getByText("10")).toBeTruthy();
    expect(screen.getByText("2")).toBeTruthy();
  });

  it("renders a compact query coverage alert when DB coverage is low", async () => {
    vi.mocked(api.health).mockResolvedValue({
      ok: false,
      db: "up",
      scheduler_lag_seconds: 12,
      last_full_scan_at: "2026-05-14T14:20:42Z",
      reason: "record coverage below expected: flow_events",
      worker_lag_seconds: 1,
      scheduler_heartbeat_lag_seconds: 1,
      scheduler_heartbeat_name: "worker",
      rescan_heartbeat_lag_seconds: 1,
      spot_refresh_heartbeat_lag_seconds: 1,
      spot_quote_lag_seconds: 60,
      latest_spot_quote_at: "2026-05-14T14:19:42Z",
      latest_spot_quote_fetched_at: "2026-05-14T14:20:42Z",
      watchlist_size: 97,
      source: "UnusualWhales",
      latency_p95_ms: 88,
      http_2xx: 120,
      http_4xx: 0,
      http_5xx: 0,
      uw_today: 40,
      cache_hit_pct: null,
      throughput_window_minutes: 15,
      record_health_ok: false,
      record_health: [
        {
          table: "flow_events",
          window_start: "2026-05-14T06:20:42Z",
          expected_tickers: 97,
          expected_min_tickers: 88,
          actual_tickers: 20,
          expected_min_rows: 88,
          actual_rows: 1234,
          latest_at: "2026-05-14T14:20:42Z",
          ok: false,
        },
      ],
    });

    render(<HealthPanel />);

    await waitFor(() => expect(screen.getByText("Query Coverage")).toBeTruthy());
    expect(screen.getByText("ALERT")).toBeTruthy();
  });
});
