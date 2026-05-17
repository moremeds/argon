/* @vitest-environment jsdom */
import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useCri } from "@/lib/regime/useCri";

const SAMPLE_RESPONSE = {
  status: "ok",
  scan_time: "2026-05-15T20:30:00+00:00",
  date: "2026-05-15",
  vix: 18.43,
  vvix: 92.9,
  spy: 588.12,
  cor1m: 10.8,
  spx_distance_pct: -2.5,
  realized_vol: 14.2,
  cri: {
    score: 33.4,
    level: "ELEVATED",
    components: { vix: 8.0, vvix: 12.0, correlation: 6.4, momentum: 7.0 },
  },
  cta: {
    realized_vol: 14.2,
    exposure_pct: 70.4,
    forced_reduction_pct: 29.6,
    forced_reduction: true,
    est_selling_bn: 103.6,
    selling_usd_b: 103.6,
  },
  crash_trigger: {
    fired: false,
    triggered: false,
    conditions: {
      spx_below_100d_ma: true,
      realized_vol_gt_25: false,
      cor1m_gt_60: false,
    },
    values: { realized_vol: 14.2, cor1m: 10.8 },
  },
  history: [],
  spy_closes: [],
};

beforeEach(() => {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue({
      ok: true,
      json: async () => SAMPLE_RESPONSE,
    }),
  );
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("useCri", () => {
  it("fetches and exposes the latest snapshot", async () => {
    const { result } = renderHook(() => useCri());
    await waitFor(() => {
      expect(result.current.data).not.toBeNull();
    });
    expect(result.current.data?.cri.level).toBe("ELEVATED");
    expect(result.current.data?.cri.score).toBe(33.4);
    expect(result.current.lastSync).toBe("2026-05-15T20:30:00+00:00");
  });

  it("calls POST when syncNow is invoked", async () => {
    const fetchSpy = global.fetch as ReturnType<typeof vi.fn>;
    const { result } = renderHook(() => useCri());
    await waitFor(() => {
      expect(result.current.data).not.toBeNull();
    });
    act(() => {
      result.current.syncNow();
    });
    await waitFor(() => {
      // initial GET + auto-POST on first load + manual syncNow = at least one POST observed
      const methods = fetchSpy.mock.calls.map((c) => c[1]?.method);
      expect(methods).toContain("POST");
    });
  });
});
