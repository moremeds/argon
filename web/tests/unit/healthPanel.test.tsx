import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { HealthPanel } from "@/components/shared/HealthPanel";
import { api } from "@/lib/api";

vi.mock("@/lib/api", () => ({
  api: {
    health: vi.fn(),
    healthBenchmarkCurrent: vi.fn(),
  },
}));

// The panel ships collapsed by default; existing assertions cover the
// expanded surface, so we click open before each check.
async function expandPanel() {
  const toggle = await screen.findByRole("button", { name: /status/i });
  fireEvent.click(toggle);
}

describe("HealthPanel", () => {
  // jsdom in this toolchain ships an empty Storage prototype; stub a
  // Map-backed shim so the panel's localStorage reads + writes work.
  beforeEach(() => {
    const store = new Map<string, string>();
    vi.stubGlobal("localStorage", {
      getItem: (k: string) => (store.has(k) ? store.get(k)! : null),
      setItem: (k: string, v: string) => {
        store.set(k, String(v));
      },
      removeItem: (k: string) => {
        store.delete(k);
      },
      clear: () => store.clear(),
      key: (i: number) => Array.from(store.keys())[i] ?? null,
      get length() {
        return store.size;
      },
    });
  });

  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
    vi.unstubAllGlobals();
    // Guard against a fake-timer test leaking into the real-timer tests that
    // rely on testing-library's waitFor.
    vi.useRealTimers();
  });

  it("opens a benchmark view from the expanded panel and fetches lazily", async () => {
    vi.mocked(api.health).mockResolvedValue({
      ok: true,
      db: "up",
      scheduler_lag_seconds: 1,
      last_full_scan_at: "2026-05-14T14:20:42Z",
      reason: null,
      worker_lag_seconds: 1,
      scheduler_heartbeat_lag_seconds: 1,
      scheduler_heartbeat_name: "worker",
      rescan_heartbeat_lag_seconds: 1,
      spot_quote_lag_seconds: 60,
      latest_spot_quote_at: "2026-05-14T14:19:42Z",
      latest_spot_quote_fetched_at: "2026-05-14T14:20:42Z",
      watchlist_size: 97,
      source: "UnusualWhales",
      version: "0.0.0-test",
      latency_p95_ms: 88,
      http_2xx: 120,
      http_4xx: 0,
      http_5xx: 0,
      uw_today: 40,
      cache_hit_pct: null,
      throughput_window_minutes: 15,
      record_health_ok: true,
      record_health: [],
      workers: [],
    });
    vi.mocked(api.healthBenchmarkCurrent).mockResolvedValue({
      captured_at: "2026-05-25T12:00:00Z",
      score: 87,
      status: "OK",
      subscores: {
        freshness: 92,
        coverage: 88,
        throughput: 81,
        provider: 90,
        worker: 100,
        persistence: 75,
      },
      metrics: {
        watchlist_size: 102,
        scanner_fresh_count: 91,
        scanner_stale_count: 7,
        scanner_dead_count: 4,
        scanner_never_scanned_count: 0,
      },
      bottleneck: {
        component: "persistence",
        severity: "degraded",
        message: "2 record-health tables below expected coverage",
        penalty: 25,
      },
      reasons: [],
    });

    render(<HealthPanel />);
    expect(api.healthBenchmarkCurrent).not.toHaveBeenCalled();
    await expandPanel();
    fireEvent.click(await screen.findByRole("button", { name: "Benchmark" }));

    await waitFor(() =>
      expect(api.healthBenchmarkCurrent).toHaveBeenCalledOnce(),
    );
    expect(screen.getByText("Pipeline Benchmark")).toBeTruthy();
    expect(screen.getByText("87")).toBeTruthy();
    expect(screen.getByText("OK")).toBeTruthy();
    expect(screen.getByText("Freshness")).toBeTruthy();
    expect(screen.getByText("Persistence")).toBeTruthy();
    expect(
      screen.getByText("2 record-health tables below expected coverage"),
    ).toBeTruthy();
  });

  it("renders a compact benchmark fallback when the request fails", async () => {
    vi.mocked(api.health).mockResolvedValue({
      ok: true,
      db: "up",
      scheduler_lag_seconds: 1,
      last_full_scan_at: "2026-05-14T14:20:42Z",
      reason: null,
      worker_lag_seconds: 1,
      scheduler_heartbeat_lag_seconds: 1,
      scheduler_heartbeat_name: "worker",
      rescan_heartbeat_lag_seconds: 1,
      spot_quote_lag_seconds: 60,
      latest_spot_quote_at: "2026-05-14T14:19:42Z",
      latest_spot_quote_fetched_at: "2026-05-14T14:20:42Z",
      watchlist_size: 97,
      source: "UnusualWhales",
      version: "0.0.0-test",
      latency_p95_ms: 88,
      http_2xx: 120,
      http_4xx: 0,
      http_5xx: 0,
      uw_today: 40,
      cache_hit_pct: null,
      throughput_window_minutes: 15,
      record_health_ok: true,
      record_health: [],
      workers: [],
    });
    vi.mocked(api.healthBenchmarkCurrent).mockRejectedValue(new Error("down"));

    render(<HealthPanel />);
    await expandPanel();
    fireEvent.click(await screen.findByRole("button", { name: "Benchmark" }));

    await waitFor(() =>
      expect(screen.getByText("Benchmark unavailable")).toBeTruthy(),
    );
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
      spot_quote_lag_seconds: 60,
      latest_spot_quote_at: "2026-05-14T14:19:42Z",
      latest_spot_quote_fetched_at: "2026-05-14T14:20:42Z",
      watchlist_size: 97,
      source: "UnusualWhales",
      version: "0.0.0-test",
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
    await expandPanel();

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

  it("keeps the last-good status on a transient failed poll, then goes OFFLINE after repeated failures", async () => {
    vi.useFakeTimers();
    const good = {
      ok: true,
      db: "up",
      scheduler_lag_seconds: 12,
      last_full_scan_at: "2026-05-14T14:20:42Z",
      reason: null,
      worker_lag_seconds: 1,
      scheduler_heartbeat_lag_seconds: 1,
      scheduler_heartbeat_name: "worker",
      rescan_heartbeat_lag_seconds: 8,
      spot_quote_lag_seconds: 60,
      latest_spot_quote_at: "2026-05-14T14:19:42Z",
      latest_spot_quote_fetched_at: "2026-05-14T14:20:42Z",
      watchlist_size: 97,
      source: "UnusualWhales",
      version: "0.0.0-test",
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
      workers: [],
    };
    vi.mocked(api.health)
      .mockResolvedValueOnce(good)
      .mockRejectedValue(new Error("timeout"));

    render(<HealthPanel />);
    fireEvent.click(screen.getByRole("button", { name: /status/i }));
    // Flush the initial (successful) poll. State updates from the resolved
    // fetch must settle inside act(), so advance timers within act().
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    const apiRow = () => screen.getByText("API").parentElement as HTMLElement;
    expect(within(apiRow()).getByText("ONLINE")).toBeTruthy();

    // Poll #1 fails — panel must keep the last-good ONLINE, not flicker OFFLINE.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(5000);
    });
    expect(within(apiRow()).getByText("ONLINE")).toBeTruthy();

    // Polls #2 and #3 fail — three consecutive misses is a real outage.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(10000);
    });
    expect(within(apiRow()).getByText("OFFLINE")).toBeTruthy();

    vi.useRealTimers();
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
      spot_quote_lag_seconds: null,
      latest_spot_quote_at: null,
      latest_spot_quote_fetched_at: null,
      watchlist_size: null,
      source: "UnusualWhales",
      version: "0.0.0-test",
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
    await expandPanel();

    await waitFor(() =>
      expect(screen.getAllByText("UNKNOWN").length).toBeGreaterThanOrEqual(2),
    );
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
        spot_quote_lag_seconds: 60,
        latest_spot_quote_at: "2026-05-14T14:19:42Z",
        latest_spot_quote_fetched_at: "2026-05-14T14:20:42Z",
        watchlist_size: 97,
        source: "UnusualWhales",
        version: "0.0.0-test",
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
        spot_quote_lag_seconds: 60,
        latest_spot_quote_at: "2026-05-14T14:19:42Z",
        latest_spot_quote_fetched_at: "2026-05-14T14:20:42Z",
        watchlist_size: 97,
        source: "Massive.com",
        version: "0.0.0-test",
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
    await expandPanel();

    await waitFor(() =>
      expect(api.health).toHaveBeenCalledWith(
        "uw",
        {
          recordMinCoverage: 0.9,
          recordWindowHours: 8,
        },
        expect.objectContaining({ signal: expect.any(AbortSignal) }),
      ),
    );
    fireEvent.change(screen.getByRole("combobox", { name: "Source" }), {
      target: { value: "massive" },
    });

    await waitFor(() =>
      expect(api.health).toHaveBeenCalledWith(
        "massive",
        {
          recordMinCoverage: 0.9,
          recordWindowHours: 8,
        },
        expect.objectContaining({ signal: expect.any(AbortSignal) }),
      ),
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
      spot_quote_lag_seconds: 60,
      latest_spot_quote_at: "2026-05-14T14:19:42Z",
      latest_spot_quote_fetched_at: "2026-05-14T14:20:42Z",
      watchlist_size: 97,
      source: "UnusualWhales",
      version: "0.0.0-test",
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
    await expandPanel();

    await waitFor(() =>
      expect(screen.getByText("Query Coverage")).toBeTruthy(),
    );
    // ALERT appears twice when records are unhealthy: once in the always-on
    // summary chip at the top, once on the Query Coverage row.
    expect(screen.getAllByText("ALERT").length).toBeGreaterThanOrEqual(1);
  });

  it("starts collapsed, hides the body, and toggles on click", async () => {
    vi.mocked(api.health).mockResolvedValue({
      ok: true,
      db: "up",
      scheduler_lag_seconds: 1,
      last_full_scan_at: "2026-05-14T14:20:42Z",
      reason: null,
      worker_lag_seconds: 1,
      scheduler_heartbeat_lag_seconds: 1,
      scheduler_heartbeat_name: "worker",
      rescan_heartbeat_lag_seconds: 1,
      spot_quote_lag_seconds: 60,
      latest_spot_quote_at: "2026-05-14T14:19:42Z",
      latest_spot_quote_fetched_at: "2026-05-14T14:20:42Z",
      watchlist_size: 97,
      source: "UnusualWhales",
      version: "0.0.0-test",
      latency_p95_ms: 88,
      http_2xx: 120,
      http_4xx: 0,
      http_5xx: 0,
      uw_today: 40,
      cache_hit_pct: null,
      throughput_window_minutes: 15,
      record_health_ok: true,
      record_health: [],
      workers: [],
    });

    render(<HealthPanel />);

    // Collapsed by default — header button visible, body hidden.
    const toggle = await screen.findByRole("button", { name: /status/i });
    expect(toggle.getAttribute("aria-expanded")).toBe("false");
    expect(screen.queryByText("Query Coverage")).toBeNull();
    expect(screen.queryByText("Watchlist")).toBeNull();

    fireEvent.click(toggle);

    await waitFor(() =>
      expect(screen.getByText("Query Coverage")).toBeTruthy(),
    );
    expect(toggle.getAttribute("aria-expanded")).toBe("true");

    // Click again to collapse; localStorage persists the choice.
    fireEvent.click(toggle);
    await waitFor(() =>
      expect(screen.queryByText("Query Coverage")).toBeNull(),
    );
    expect(window.localStorage.getItem("uw_health_collapsed")).toBe("1");
  });

  it("shows the deployed version tag in the collapsed header", async () => {
    vi.mocked(api.health).mockResolvedValue({
      ok: true,
      db: "up",
      version: "1.2.3",
      source: "UnusualWhales",
      throughput_window_minutes: 15,
    });

    render(<HealthPanel />);

    // Tag rides the always-visible header — no need to expand the panel.
    const toggle = await screen.findByRole("button", { name: /status/i });
    await waitFor(() => expect(toggle.textContent).toContain("v1.2.3"));
    expect(toggle.getAttribute("aria-expanded")).toBe("false");
  });
});
