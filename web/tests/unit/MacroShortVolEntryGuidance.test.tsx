/* @vitest-environment jsdom */
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/regime/useVrpMacroLive", () => ({
  useVrpMacroLive: () => ({
    data: {
      status: "ok",
      basis: "eod",
      active_source: null,
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
          // deepest-OTM wing: no NBBO from IB or UW, so no IV could be marked
          // and greeks were never computed (the real "unquoted" shape)
          leg: "wing_below",
          strike: 6590,
          nbbo_bid: null,
          nbbo_ask: null,
          iv: null,
          delta: 0,
          source: "uw",
          greeks_source: "none",
        },
      ],
    },
    loading: false,
    error: null,
  }),
}));

import MacroShortVolEntryGuidance from "@/components/regime/MacroShortVolEntryGuidance";

afterEach(() => {
  vi.restoreAllMocks();
});

describe("MacroShortVolEntryGuidance", () => {
  it("renders the tracked-entry card: ETD + the 4 bracketing strikes", () => {
    render(<MacroShortVolEntryGuidance />);
    expect(screen.getByTestId("macro-shortvol-entry-card")).toBeTruthy();
    expect(screen.getByText(/2026-08-07/)).toBeTruthy(); // ETD
    expect(screen.getByText("6900")).toBeTruthy(); // 0.25↑ short
    expect(screen.getByText("6600")).toBeTruthy(); // 0.125↑ wing
    expect(screen.getByTestId("entry-leg-wing_below")).toBeTruthy();
  });

  it("renders leg deltas to 3 decimals", () => {
    render(<MacroShortVolEntryGuidance />);
    // short_below delta -0.255 must keep its third digit, not round to -0.26
    expect(screen.getByText("-0.255")).toBeTruthy();
  });

  it("shows — (not a fabricated 0Δ) for a leg whose greeks weren't computed", () => {
    render(<MacroShortVolEntryGuidance />);
    // wing_below: no NBBO, no IV, greeks_source "none" → mid AND delta are
    // unavailable. They must render em-dash, never the uninitialised 0.000.
    const cells = screen
      .getByTestId("entry-leg-wing_below")
      .querySelectorAll("td");
    expect(cells[2].textContent).toBe("—"); // mid
    expect(cells[3].textContent).toBe("—"); // delta
  });

  it("folds in the guidance table and a live $60k-unit sizing line", () => {
    render(<MacroShortVolEntryGuidance />);
    // static backtest table sits in the larger card
    expect(screen.getByText(/GUIDANCE · SPX DIRECT/i)).toBeTruthy();
    expect(screen.getByText("14.2%")).toBeTruthy(); // brp 0.20 CAGR row
    // live line: max_loss = (6900 − 6600) − 30 = 270 pts → $27.0k margin,
    // 45% of $60k; floor(0.50 × 60000 / 27000) = 1 spread at brp 0.50.
    const note = screen.getByTestId("macro-shortvol-unit-sizing");
    expect(note.textContent).toContain("$60k unit");
    expect(note.textContent).toContain("27.0k");
    expect(note.textContent).toContain("45% of $60k");
    expect(note.textContent).toContain("brp 0.50: 1");
  });

  it("POSTs to capture on click and shows the captured badge", async () => {
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValue(
        new Response(JSON.stringify({ entry_id: 42 }), { status: 200 }),
      );
    render(<MacroShortVolEntryGuidance />);
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
