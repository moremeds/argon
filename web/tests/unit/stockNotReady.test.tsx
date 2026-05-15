/* @vitest-environment jsdom */
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import StockLayout from "@/app/stock/[ticker]/layout";
import TabPage from "@/app/stock/[ticker]/[tab]/page";
import { api } from "@/lib/api";

vi.mock("next/navigation", () => ({
  notFound: vi.fn(() => {
    throw new Error("not found");
  }),
  usePathname: () => "/stock/SOXX/market-structure",
}));

vi.mock("@/lib/api", () => ({
  api: {
    stock: vi.fn(),
  },
}));

function noRunsError(ticker: string) {
  return new Error(
    `API 404 for /api/stock/${ticker}: {"detail":"no runs for ${ticker}"}`,
  );
}

describe("stock not-ready state", () => {
  it("renders a not-ready popup from the stock layout when a ticker has no scan run", async () => {
    vi.mocked(api.stock).mockRejectedValueOnce(noRunsError("SOXX"));

    render(
      await StockLayout({
        children: <div>stock child</div>,
        params: Promise.resolve({ ticker: "SOXX" }),
      }),
    );

    expect(screen.getByText("SOXX is not ready")).not.toBeNull();
    expect(screen.queryByText("stock child")).toBeNull();
  });

  it("renders a not-ready popup from report tabs when a ticker has no scan run", async () => {
    vi.mocked(api.stock).mockRejectedValueOnce(noRunsError("SOXX"));

    render(
      await TabPage({
        params: Promise.resolve({ ticker: "SOXX", tab: "market-structure" }),
      }),
    );

    expect(screen.getByText("SOXX is not ready")).not.toBeNull();
  });
});
