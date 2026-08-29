import { afterEach, describe, expect, it, vi } from "vitest";

import { api } from "@/lib/api";

function stubFetch(response: unknown) {
  const spy = vi.fn().mockResolvedValue(response);
  vi.stubGlobal("fetch", spy);
  return spy;
}

describe("gold API client", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("settles a 404 to null — the engine has not run is a fact, not an error", async () => {
    stubFetch({ ok: false, status: 404, text: () => Promise.resolve("") });

    await expect(api.goldState()).resolves.toBeNull();
  });

  it("rejects a non-404 so the page can say the request failed", async () => {
    stubFetch({
      ok: false,
      status: 500,
      text: () => Promise.resolve("database unavailable"),
    });

    await expect(api.goldState()).rejects.toThrow(
      "API 500 for /api/gold/state: database unavailable",
    );
  });

  it("rejects when the API cannot be reached at all", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockRejectedValue(new TypeError("fetch failed")),
    );

    await expect(api.goldState()).rejects.toThrow("fetch failed");
  });

  it("sends the replay date as the as_of QUERY param, not a path segment", async () => {
    const spy = stubFetch({
      ok: true,
      status: 200,
      text: () => Promise.resolve("{}"),
    });

    await api.goldReplay("2026-08-14");

    expect(spy.mock.calls[0][0]).toContain("/api/gold/replay?as_of=2026-08-14");
  });

  it("requests a typed gold lens detail by its bounded lens id", async () => {
    const spy = stubFetch({
      ok: true,
      status: 200,
      text: () =>
        Promise.resolve(
          JSON.stringify({ lens_id: "structural", posture: {}, detail: {} }),
        ),
    });

    await api.goldLens("structural");

    expect(spy.mock.calls[0][0]).toContain("/api/gold/lenses/structural");
  });
});
