import { afterEach, describe, expect, it, vi } from "vitest";
import { api } from "@/lib/api";

describe("health benchmark API client", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("fetches the current pipeline benchmark", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        text: () =>
          Promise.resolve(
            JSON.stringify({
              captured_at: "2026-05-25T12:00:00Z",
              score: 87,
              status: "OK",
              subscores: {},
              metrics: {},
              bottleneck: null,
              reasons: [],
            }),
          ),
      }),
    );

    await api.healthBenchmarkCurrent();

    expect(fetch).toHaveBeenCalledWith(
      "http://127.0.0.1:8400/api/health/benchmark/current",
      expect.objectContaining({ cache: "no-store" }),
    );
  });

  it("fetches benchmark history for the requested hour window", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        text: () => Promise.resolve(JSON.stringify({ snapshots: [] })),
      }),
    );

    await api.healthBenchmarkHistory(24);

    expect(fetch).toHaveBeenCalledWith(
      "http://127.0.0.1:8400/api/health/benchmark/history?hours=24",
      expect.objectContaining({ cache: "no-store" }),
    );
  });
});
