/* @vitest-environment jsdom */
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { TickerCard } from "@/components/watchlist/TickerCard";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ refresh: vi.fn() }),
}));

const card = {
  ticker: "TSLA",
  sector: "Technology",
  pinned: false,
  sort_rank: 0,
  spot: "445.12",
  spot_quoted_at: "2026-05-14T00:54:48Z",
  spot_source: "massive.com_intraday",
  scanned_at: "2026-05-14T00:44:48Z",
  iv_atm: "0.691",
  iv_rank: "39.0",
  setup: { type: "C", direction: "bear", score: "1.51" },
  aggression_pct: "0.91",
  returns: { d1: "0.01", w1: "0.02", d30: "-0.03" },
  gamma: {
    flip_distance: "0.05",
    flip_price: "420",
    per_1pct_move: "1000",
    max_strike: "450",
    expiring_pct: "0.20",
    expiring_date: "2026-05-15",
  },
  skew: { rr25d_30dte: "-0.0146" },
  positioning: {
    call_oi: 1200000,
    put_oi: 2100000,
    pcr_oi: "1.75",
    pcr_vol: "1.58",
    pcr_delta_30d: "-0.03",
  },
};

describe("TickerCard", () => {
  it("shows full quoted and analytics timestamps with timezone", () => {
    render(<TickerCard card={card} sparkline={[440, 445]} />);

    expect(screen.getByText(/spot /).textContent).toMatch(
      /2026.*\d{2}:\d{2}:\d{2}.*(?:UTC|GMT|[A-Z]{2,5})/,
    );
    expect(screen.getByText(/analytics /).textContent).toMatch(
      /2026.*\d{2}:\d{2}:\d{2}.*(?:UTC|GMT|[A-Z]{2,5})/,
    );
  });
});
