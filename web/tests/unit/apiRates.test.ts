import { afterEach, describe, expect, it, vi } from "vitest";
import { api } from "@/lib/api";

describe("rates API client", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("returns null when the rates snapshot fetch cannot reach the API", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockRejectedValue(new TypeError("fetch failed")),
    );

    await expect(api.ratesSnapshot()).resolves.toBeNull();
  });

  it("still rejects non-404 API errors", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: false,
        status: 500,
        text: () => Promise.resolve("database unavailable"),
      }),
    );

    await expect(api.ratesSnapshot()).rejects.toThrow(
      "API 500 for /api/rates/snapshot: database unavailable",
    );
  });
});
