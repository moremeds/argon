/* @vitest-environment jsdom */
import { render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { CardGrid } from "@/components/watchlist/CardGrid";

vi.mock("@/components/watchlist/TickerCard", () => ({
  TickerCard: ({ card }: { card: { ticker: string } }) => (
    <div data-testid="ticker-card">{card.ticker}</div>
  ),
}));

const baseCard = {
  pinned: false,
  spot: null,
  spot_quoted_at: null,
  spot_source: null,
  scanned_at: null,
  iv_atm: null,
  iv_rank: null,
  setup: { type: null, direction: null, score: null },
  aggression_pct: null,
  returns: { d1: null, w1: null, d30: null },
  gamma: {
    flip_distance: null,
    flip_price: null,
    per_1pct_move: null,
    max_strike: null,
    expiring_pct: null,
    expiring_date: null,
  },
  skew: { rr25d_30dte: null },
  positioning: {
    call_oi: null,
    put_oi: null,
    pcr_oi: null,
    pcr_vol: null,
    pcr_delta_30d: null,
  },
  queue: null,
};

function card(
  ticker: string,
  sector: string,
  sortRank: number,
  marketCap: string | null,
  aum: string | null = null,
) {
  return {
    ...baseCard,
    ticker,
    sector,
    sort_rank: sortRank,
    market_cap: marketCap,
    aum,
  };
}

describe("CardGrid", () => {
  it("orders all-sector groups by dashboard priority and cards by market cap", () => {
    render(
      <CardGrid
        data={{
          scanned_at_min: null,
          scanned_at_max: null,
          scheduler_lag_seconds: null,
          queue: { total: 0, queued: 0, running: 0, oldest_requested_at: null },
          tickers: [
            card("UNH", "Healthcare", 0, "500"),
            card("HUT", "NeoCloud", 0, "4"),
            card("AMD", "Semiconductor", 301, "300"),
            card("TSLA", "M7", 206, "900"),
            card("QQQ", "ETF", 102, "250", "600"),
            card("AAPL", "M7", 201, "3000"),
            card("SPY", "ETF", 101, "500", "400"),
            card("AVGO", "Semiconductor", 302, "1200"),
          ],
        }}
      />,
    );

    expect(screen.getAllByRole("heading").map((h) => h.textContent)).toEqual([
      "ETF · 2",
      "M7 · 2",
      "Semiconductor · 2",
      "Healthcare · 1",
      "NeoCloud · 1",
    ]);

    const sections = screen.getAllByRole("heading").map((heading) => {
      const section = heading.closest("section");
      expect(section).not.toBeNull();
      return within(section as HTMLElement)
        .getAllByTestId("ticker-card")
        .map((item) => item.textContent);
    });

    expect(sections).toEqual([
      ["QQQ", "SPY"],
      ["AAPL", "TSLA"],
      ["AVGO", "AMD"],
      ["UNH"],
      ["HUT"],
    ]);
  });

  it("places pinned cards first within their sector regardless of size", () => {
    render(
      <CardGrid
        data={{
          scanned_at_min: null,
          scanned_at_max: null,
          scheduler_lag_seconds: null,
          queue: { total: 0, queued: 0, running: 0, oldest_requested_at: null },
          tickers: [
            { ...card("AAPL", "M7", 201, "3000"), pinned: false },
            { ...card("TSLA", "M7", 206, "900"), pinned: true },
          ],
        }}
      />,
    );

    const section = screen
      .getByRole("heading")
      .closest("section") as HTMLElement;
    const order = within(section)
      .getAllByTestId("ticker-card")
      .map((el) => el.textContent);

    expect(order).toEqual(["TSLA", "AAPL"]);
  });

  it("orders non-priority sectors by their members' max market cap (descending)", () => {
    render(
      <CardGrid
        data={{
          scanned_at_min: null,
          scanned_at_max: null,
          scheduler_lag_seconds: null,
          queue: { total: 0, queued: 0, running: 0, oldest_requested_at: null },
          tickers: [
            // sort_rank says Banks first (400 < 420), but Healthcare has the
            // bigger member by size (500B vs 1B) so the new ordering puts it
            // ahead. Priority prefix (ETF) stays first either way.
            card("XLF", "Banks", 400, "1000000000"),
            card("JNJ", "Healthcare", 420, "500000000000"),
            card("SPY", "ETF", 101, "300000000000"),
          ],
        }}
      />,
    );

    expect(screen.getAllByRole("heading").map((h) => h.textContent)).toEqual([
      "ETF · 1",
      "Healthcare · 1",
      "Banks · 1",
    ]);
  });

  it("breaks final ties alphabetically by ticker when nothing else differs", () => {
    render(
      <CardGrid
        data={{
          scanned_at_min: null,
          scanned_at_max: null,
          scheduler_lag_seconds: null,
          queue: { total: 0, queued: 0, running: 0, oldest_requested_at: null },
          tickers: [
            card("ZZZ", "ETF", 100, null),
            card("AAA", "ETF", 100, null),
          ],
        }}
      />,
    );

    const section = screen
      .getByRole("heading")
      .closest("section") as HTMLElement;
    const order = within(section)
      .getAllByTestId("ticker-card")
      .map((el) => el.textContent);

    expect(order).toEqual(["AAA", "ZZZ"]);
  });
});
