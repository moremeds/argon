/* @vitest-environment jsdom */
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
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

vi.mock("@/lib/regime/useVrpMacroEntryPreview", () => ({
  useVrpMacroEntryPreview: () => ({
    data: {
      name: "SPX",
      as_of: null,
      spot: 7500,
      expiry: "2026-08-07",
      hold_days: 30,
      action: "SKIP",
      vrp_z: -1.95,
      weight: 0,
      modeled_credit: 30,
      legs: [
        {
          leg: "short_above",
          strike: 6900,
          nbbo_bid: 40,
          nbbo_ask: 41,
          delta: -0.25,
          source: "modeled",
          greeks_source: "bs",
        },
        {
          leg: "short_below",
          strike: 6890,
          nbbo_bid: 39,
          nbbo_ask: 40,
          delta: -0.255,
          source: "modeled",
          greeks_source: "bs",
        },
        {
          leg: "wing_above",
          strike: 6600,
          nbbo_bid: 20,
          nbbo_ask: 21,
          delta: -0.125,
          source: "modeled",
          greeks_source: "bs",
        },
        {
          leg: "wing_below",
          strike: 6590,
          nbbo_bid: 19,
          nbbo_ask: 20,
          delta: -0.13,
          source: "modeled",
          greeks_source: "bs",
        },
      ],
    },
    loading: false,
    error: null,
  }),
}));

import MacroShortVolCard from "@/components/regime/MacroShortVolCard";

afterEach(() => {
  vi.restoreAllMocks();
});

describe("MacroShortVolCard", () => {
  it("renders SKIP + the live vrp_z and weight when weight is 0", () => {
    render(<MacroShortVolCard />);
    expect(screen.getByText(/SKIP/i)).toBeTruthy();
    expect(screen.getByText(/-1\.95/)).toBeTruthy();
    expect(screen.getByText(/weight 0\.00/)).toBeTruthy();
  });

  it("drops the (gate at 0) and stand-aside copy", () => {
    render(<MacroShortVolCard />);
    expect(screen.queryByText(/gate at 0/i)).toBeNull();
    expect(screen.queryByText(/stand aside/i)).toBeNull();
  });

  it("renders the tracked-entry panel: ETD + the 4 bracketing strikes", () => {
    render(<MacroShortVolCard />);
    expect(screen.getByText(/2026-08-07/)).toBeTruthy(); // ETD
    expect(screen.getByText("6900")).toBeTruthy(); // 0.25↑ short
    expect(screen.getByText("6600")).toBeTruthy(); // 0.125↑ wing
    expect(screen.getByTestId("entry-leg-wing_below")).toBeTruthy();
  });

  it("POSTs to capture on click and shows the captured badge", async () => {
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValue(
        new Response(JSON.stringify({ entry_id: 42 }), { status: 200 }),
      );
    render(<MacroShortVolCard />);
    fireEvent.click(screen.getByTestId("capture-entry-btn"));
    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledTimes(1);
    });
    expect(fetchMock.mock.calls[0][0]).toContain(
      "/api/regime/vrp-macro-signal/entry/capture",
    );
    expect(fetchMock.mock.calls[0][1]).toMatchObject({ method: "POST" });
    expect(await screen.findByText(/Captured #42/)).toBeTruthy();
  });
});
