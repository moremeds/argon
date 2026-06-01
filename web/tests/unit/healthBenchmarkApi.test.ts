import { afterEach, describe, expect, it, vi } from "vitest";
import { api } from "@/lib/api";

// In jsdom (`typeof window !== "undefined"`), `lib/api.ts` resolves its base
// URL to "" so calls become relative — they get routed through the Next.js
// `/api/:path*` rewrite to FastAPI in production. These assertions exercise
// the browser-bundle contract.
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
      "/api/health/benchmark/current",
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
      "/api/health/benchmark/history?hours=24",
      expect.objectContaining({ cache: "no-store" }),
    );
  });
});
