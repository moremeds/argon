/* @vitest-environment jsdom */
import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useVcg } from "@/lib/regime/useVcg";

const SAMPLE_RESPONSE = {
  status: "ok",
  scan_time: "2026-05-15T20:30:00+00:00",
  date: "2026-05-15",
  credit_proxy: "HYG",
  signal: {
    vcg: 2.85,
    vcg_adj: 2.85,
    residual: -0.0012,
    beta1_vvix: -0.05,
    beta2_vix: -0.03,
    alpha: 0.0001,
    vix: 30.2,
    vvix: 125.0,
    credit_price: 78.4,
    credit_5d_return_pct: -1.2,
    ro: 1,
    edr: 1,
    tier: 1,
    bounce: 0,
    vvix_severity: "extreme",
    sign_ok: true,
    sign_suppressed: false,
    pi_panic: 0.0,
    regime: "DIVERGENCE",
    interpretation: "RISK_OFF",
    attribution: {
      vvix_pct: 60.0,
      vix_pct: 40.0,
      vvix_component: -0.001,
      vix_component: -0.0006,
      model_implied: -0.00159,
    },
  },
  history: [],
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

describe("useVcg", () => {
  it("fetches and exposes the latest snapshot", async () => {
    const { result } = renderHook(() => useVcg());
    await waitFor(() => {
      expect(result.current.data).not.toBeNull();
    });
    expect(result.current.data?.signal?.interpretation).toBe("RISK_OFF");
    expect(result.current.data?.signal?.vcg).toBe(2.85);
    expect(result.current.data?.credit_proxy).toBe("HYG");
    expect(result.current.lastSync).toBe("2026-05-15T20:30:00+00:00");
  });

  it("calls POST against the /vcg/scan URL when syncNow is invoked", async () => {
    const fetchSpy = global.fetch as ReturnType<typeof vi.fn>;
    const { result } = renderHook(() => useVcg());
    await waitFor(() => {
      expect(result.current.data).not.toBeNull();
    });
    act(() => {
      result.current.syncNow();
    });
    await waitFor(() => {
      const posts = fetchSpy.mock.calls.filter((c) => c[1]?.method === "POST");
      expect(posts.length).toBeGreaterThan(0);
      // POSTs must target the scan path, not the GET URL — protects against
      // a 405 silent-fail regression.
      for (const [url] of posts) {
        expect(String(url)).toMatch(/\/api\/regime\/vcg\/scan$/);
      }
    });
  });
});
