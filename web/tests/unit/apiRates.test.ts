import { afterEach, describe, expect, it, vi } from "vitest";
import { api } from "@/lib/api";

describe("rates API client", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("rejects when the rates snapshot fetch cannot reach the API", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockRejectedValue(new TypeError("fetch failed")),
    );

    await expect(api.ratesSnapshot()).rejects.toThrow("fetch failed");
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

  it("sends no query at all when live, and `as_of` only when replaying", () => {
    // The live URL must stay byte-identical. `routers/rates.py:51` passes `None` down
    // unless a date was actually asked for, precisely so a snapshot whose `computed_at`
    // sits a second in the future cannot 404 the page — sending `as_of=` (or today's
    // date) from the client would give that guard nothing to guard.
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      text: () => Promise.resolve("{}"),
    });
    vi.stubGlobal("fetch", fetchMock);

    void api.ratesSnapshot();
    void api.ratesSnapshot("");
    void api.ratesSnapshot("2026-08-20");
    void api.macroPolicy();
    void api.macroPolicy("2026-08-20");
    void api.macroContextSnapshot();
    void api.macroContextSnapshot("2026-08-20");

    // Relative, because these tests run under jsdom and `lib/api.ts` resolves its base
    // per environment: "" in a browser (the next.config.mjs rewrite proxies it), the
    // absolute FastAPI origin in an RSC fetch. Only the path and query are P4's subject.
    const urls = fetchMock.mock.calls.map(([url]) => String(url));
    expect(urls).toEqual([
      "/api/rates/snapshot",
      "/api/rates/snapshot",
      "/api/rates/snapshot?as_of=2026-08-20",
      "/api/macro/policy",
      "/api/macro/policy?as_of=2026-08-20",
      "/api/macro/snapshot",
      "/api/macro/snapshot?as_of=2026-08-20",
    ]);
  });
});
