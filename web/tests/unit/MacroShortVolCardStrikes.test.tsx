/* @vitest-environment jsdom */
import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

// Frozen real prod SPX readout for 2026-09-18 (spot 7637.76, ATM iv 0.1544).
// The listed-skew row is what the strike grid actually resolves; the flat-vol
// row is the modeled fallback a name without a grid gets.
const BASE = {
  name: "SPX",
  snapshot_date: "2026-09-18",
  as_of: "2026-09-18",
  spot: 7637.76,
  iv: 0.1544,
  rv20: 0.1,
  vrp: 0.054,
  vrp_z: 1.2,
  weight: 1,
  action: "TRADE",
  put_width: 290,
  credit: 28.5,
  max_loss: 261.5,
  hold_days: 30,
  short_delta: 0.25,
  wing_delta: 0.125,
};

const signal = { current: {} as Record<string, unknown> };

vi.mock("@/lib/regime/useVrpMacroLive", () => ({
  useVrpMacroLive: () => ({
    data: {
      status: "ok",
      basis: "eod",
      live_quotes: {},
      signal: signal.current,
    },
    loading: false,
    error: null,
  }),
}));

import MacroShortVolCard from "@/components/regime/MacroShortVolCard";

afterEach(() => {
  vi.restoreAllMocks();
});

describe("MacroShortVolCard strike provenance", () => {
  it("shows the ACTUAL deltas and the expiry for a listed_skew row", () => {
    signal.current = {
      ...BASE,
      short_put: 7405,
      long_put: 7115,
      short_put_delta: 0.2489,
      long_put_delta: 0.1264,
      strike_basis: "listed_skew",
      strike_grid_date: "2026-09-18",
      expiry: "2026-10-30",
    };
    render(<MacroShortVolCard />);
    expect(
      screen.getByText(/Sell 7405 \(0\.25Δ\) \/ buy 7115 \(0\.13Δ\) put/),
    ).toBeTruthy();
    expect(screen.getByText(/Expiry 2026-10-30 · listed strikes/)).toBeTruthy();
    expect(screen.queryByText(/flat-vol model/)).toBeNull();
  });

  it("tags a flat_vol_model row and shows no per-strike delta", () => {
    signal.current = {
      ...BASE,
      name: "QQQ",
      short_put: 7405.31,
      long_put: 7228.44,
      short_put_delta: null,
      long_put_delta: null,
      strike_basis: "flat_vol_model",
      strike_grid_date: null,
      expiry: null,
    };
    render(<MacroShortVolCard />);
    expect(screen.getByText(/flat-vol model/)).toBeTruthy();
    expect(screen.queryByText(/\(0\.25Δ\)/)).toBeNull();
    expect(screen.queryByText(/listed strikes/)).toBeNull();
  });
});
