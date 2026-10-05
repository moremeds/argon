/* @vitest-environment jsdom */
import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/apiClient", () => ({
  ApiError: class ApiError extends Error {},
  apiFetch: vi.fn(),
}));

import { apiFetch } from "@/lib/apiClient";
import { useGex } from "@/lib/regime/useGex";
import { MarketState } from "@/lib/regime/useMarketHours";

const fetchMock = vi.mocked(apiFetch);
// Fri 2026-10-02 14:00 ET: a session day, mid-RTH.
const NOW = new Date("2026-10-02T14:00:00-04:00");

function gexCalls(): number {
  return fetchMock.mock.calls.filter(([url]) => String(url).includes("/gex"))
    .length;
}

async function flush(): Promise<void> {
  await act(async () => {
    await Promise.resolve();
  });
}

beforeEach(() => {
  vi.useFakeTimers();
  vi.setSystemTime(NOW);
  fetchMock.mockReset();
});

afterEach(() => {
  vi.useRealTimers();
});

describe("useGex polling", () => {
  it("still fires the 60 s interval when the parent re-renders every 2.5 s", async () => {
    // Fresh scan → no staleness retry; only the interval can refetch.
    fetchMock.mockResolvedValue({ scan_time: NOW.toISOString() });
    const { rerender } = renderHook(() => useGex(MarketState.OPEN));
    await flush();
    const afterMount = gexCalls();

    // The regime quotes poll re-renders GexSubTab every 2.5 s.
    for (let t = 0; t < 26; t++) {
      await act(async () => {
        await vi.advanceTimersByTimeAsync(2_500);
      });
      rerender();
    }
    await flush();
    expect(gexCalls()).toBeGreaterThan(afterMount);
  });

  it("does not retry a stale scan while the market is CLOSED", async () => {
    // Yesterday's scan: needsGexRetry would be true.
    fetchMock.mockResolvedValue({ scan_time: "2026-10-01T20:00:00Z" });
    renderHook(() => useGex(MarketState.CLOSED));
    await flush();
    const afterMount = gexCalls();
    expect(afterMount).toBe(1);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(60_000);
    });
    await flush();
    expect(gexCalls()).toBe(afterMount);
  });
});
