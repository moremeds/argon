/* @vitest-environment jsdom */
import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/regime/useVrpMacroLive", () => ({
  useVrpMacroLive: () => ({
    data: {
      status: "ok",
      basis: "live",
      active_source: "xenon_ws",
      live_quotes: {},
      signal: {
        name: "SPX",
        snapshot_date: "2026-06-24",
        as_of: "2026-06-23",
        spot: 7500,
        iv: 0.16,
        rv20: 0.12,
        vrp: 0.04,
        vrp_z: -1.95,
        weight: 0,
        action: "SKIP",
        short_put: null,
        long_put: null,
        put_width: null,
        credit: null,
        max_loss: null,
        hold_days: 30,
        short_delta: 0.25,
        wing_delta: 0.125,
        bt_n: 522,
        bt_sharpe: 1.65,
        bt_maxdd: -0.8,
        bt_annror: 0.53,
        bt_calmar: 0.66,
      },
    },
    loading: false,
    error: null,
  }),
}));

import MacroShortVolCard from "@/components/regime/MacroShortVolCard";

afterEach(() => {
  vi.restoreAllMocks();
});

describe("MacroShortVolCard (action card)", () => {
  it("renders SKIP + the live vrp_z and weight when weight is 0", () => {
    render(<MacroShortVolCard />);
    expect(screen.getByText("SKIP")).toBeTruthy();
    expect(screen.getByText(/-1\.95/)).toBeTruthy();
    expect(screen.getByText(/weight 0\.00/)).toBeTruthy();
  });

  it("drops the (gate at 0) and stand-aside copy", () => {
    render(<MacroShortVolCard />);
    expect(screen.queryByText(/gate at 0/i)).toBeNull();
    expect(screen.queryByText(/stand aside/i)).toBeNull();
  });

  it("renders the bull-put structure line", () => {
    render(<MacroShortVolCard />);
    expect(
      screen.getByText(/Bull put spread 0\.25Δ\/0\.125Δ · ~30d hold/),
    ).toBeTruthy();
  });
});
