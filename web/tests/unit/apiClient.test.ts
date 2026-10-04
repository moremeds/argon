import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError, apiErrorMessage, apiFetch } from "@/lib/apiClient";
import { isStockReportNotReadyError } from "@/lib/stockNotReady";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("ApiError", () => {
  it("keeps the message the old plain Error carried (nothing user-visible changes)", () => {
    const e = new ApiError(
      404,
      "/api/stock/AAPL",
      '{"detail":"no runs for AAPL"}',
    );
    expect(e.message).toBe(
      'API 404 for /api/stock/AAPL: {"detail":"no runs for AAPL"}',
    );
    expect(e).toBeInstanceOf(Error);
    expect(e.status).toBe(404);
    expect(e.detail).toBe("no runs for AAPL");
  });

  it("has no detail for a non-JSON body", () => {
    const e = new ApiError(502, "/api/x", "<html>bad gateway</html>");
    expect(e.json).toBeNull();
    expect(e.detail).toBeUndefined();
    expect(apiErrorMessage(e)).toBe("HTTP 502");
  });

  it("apiErrorMessage prefers the API detail string", () => {
    const e = new ApiError(
      503,
      "/api/x",
      '{"detail":"run scripts/backtest_vcg.py"}',
    );
    expect(apiErrorMessage(e)).toBe("run scripts/backtest_vcg.py");
    expect(apiErrorMessage(new TypeError("Failed to fetch"))).toBe(
      "Failed to fetch",
    );
  });
});

describe("apiFetch", () => {
  it("throws ApiError on a non-2xx answer", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => new Response('{"detail":"nope"}', { status: 500 })),
    );
    await expect(apiFetch("/api/x")).rejects.toMatchObject({
      name: "ApiError",
      status: 500,
      path: "/api/x",
      detail: "nope",
    });
  });

  it("returns null for an allowed 404 and undefined for an empty body", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => new Response("", { status: 404 })),
    );
    expect(await apiFetch("/api/x", undefined, { allow404: true })).toBeNull();
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => new Response(null, { status: 204 })),
    );
    expect(await apiFetch("/api/x")).toBeUndefined();
  });

  it("sends a relative URL in the browser, no-store, JSON content type", async () => {
    const fetchMock = vi.fn(async () => new Response("{}", { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);
    await apiFetch("/api/x", { method: "POST" });
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/x",
      expect.objectContaining({
        method: "POST",
        cache: "no-store",
        headers: expect.objectContaining({
          "Content-Type": "application/json",
        }),
      }),
    );
  });
});

describe("isStockReportNotReadyError", () => {
  const notReady = (t: string) =>
    new ApiError(404, `/api/stock/${t}`, `{"detail":"no runs for ${t}"}`);

  it("matches the typed 404 'no runs' answer, case-insensitively", () => {
    expect(isStockReportNotReadyError(notReady("SOXX"), "SOXX")).toBe(true);
    expect(isStockReportNotReadyError(notReady("SOXX"), "soxx")).toBe(true);
  });

  it("rejects anything else", () => {
    // Same text, but not an ApiError: the match is typed now, not textual.
    expect(
      isStockReportNotReadyError(
        new Error('API 404 for /api/stock/SOXX: {"detail":"no runs for SOXX"}'),
        "SOXX",
      ),
    ).toBe(false);
    expect(
      isStockReportNotReadyError(
        new ApiError(500, "/api/stock/SOXX", '{"detail":"no runs for SOXX"}'),
        "SOXX",
      ),
    ).toBe(false);
    expect(
      isStockReportNotReadyError(
        new ApiError(
          404,
          "/api/stock/SOXX/history",
          '{"detail":"no runs for SOXX"}',
        ),
        "SOXX",
      ),
    ).toBe(false);
    expect(
      isStockReportNotReadyError(
        new ApiError(404, "/api/stock/SOXX", '{"detail":"unknown ticker"}'),
        "SOXX",
      ),
    ).toBe(false);
    expect(isStockReportNotReadyError(notReady("SOXX"), "SOX")).toBe(false);
  });
});
