/* @vitest-environment jsdom */
import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import DensityConePanel from "@/components/regime/DensityConePanel";

// lightweight-charts drives a real canvas through fancy-canvas, which calls
// window.matchMedia — absent in jsdom. Same approach the existing LWC pane takes
// (see technicalsTabAutofill.test.tsx): stub the chart, test the panel around it.
//
// The canvas itself is exercised by tests/e2e/regime-density.spec.ts — but note that
// spec is NOT a CI gate: CI runs `test:e2e:technicals`, whose config matches only
// technicals-tab.spec.ts. It runs under `npm run test:e2e` against a live stack. So
// rendering regressions inside the chart are caught by review and local runs, not by
// the pipeline; don't read the mock here as "covered elsewhere in CI".
vi.mock("@/components/regime/DensityConeChart", () => ({
  default: ({ view }: { view: string }) => (
    <div data-testid="spx-density-chart" data-view={view} />
  ),
}));

const BINS = {
  lo: -0.02,
  hi: 0.02,
  n_bins: 4,
  counts: [500, 4500, 4000, 1000],
  total: 10000,
  clipped: 0,
};

const HORIZON = (h: number) => ({
  h,
  target_date: `2026-08-0${h}`,
  scored_horizon: h !== 4,
  q05: -0.016,
  q10: -0.0117,
  q25: -0.0044,
  q50: 0.001,
  q75: 0.0069,
  q90: 0.0123,
  q95: 0.0154,
  baseline_q05: -0.0141,
  baseline_q10: -0.011,
  baseline_q25: -0.0058,
  baseline_q50: 0,
  baseline_q75: 0.0058,
  baseline_q90: 0.0111,
  baseline_q95: 0.0143,
  band80_width: 0.024,
  baseline_band80_width: 0.0221,
  width_ratio: 1.085,
  realised_return: null,
  inside_band80: null,
  density: BINS,
});

const LATEST = {
  forecast: {
    as_of: "2026-07-30",
    anchor_close: 7437.63,
    origin: "prospective",
    fallback_used: false,
    params: { omega: 0.039, alpha: 0.014, gamma: 0.236, beta: 0.834 },
    rows: [1, 2, 3, 4, 5].map(HORIZON),
  },
  recent_path: [
    {
      date: "2026-07-29",
      close: 7316.15,
      open: 7420.1,
      high: 7431.0,
      low: 7310.4,
    },
    // close-only session: no OHLC, must not be turned into a candle
    { date: "2026-07-30", close: 7437.63, open: null, high: null, low: null },
  ],
  gamma_levels: {
    as_of: "2026-07-30",
    spot: 7437.63,
    call_wall: 7600,
    put_wall: 7300,
    gamma_flip: 7450,
    source: "uw_gex_levels_daily",
    dropped: [],
  },
  disclaimer: "Display-only",
};

beforeEach(() => {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue({ ok: true, json: async () => LATEST }),
  );
});

describe("DensityConePanel", () => {
  it("renders the display-only chip and labels bands by their real quantile span", async () => {
    render(<DensityConePanel />);
    expect(
      await screen.findByText(/DISPLAY ONLY · NOT A TRADING SIGNAL/),
    ).toBeTruthy();
    expect(screen.getByTestId("spx-density-panel")).toBeTruthy();
    // The legend must quote OUR spans. Relabelling q05–q95 as "95% confidence"
    // would claim coverage v13 never validated.
    const legend = screen.getByTestId("cone-band-legend").textContent ?? "";
    expect(legend).toContain("90% (q05–q95)");
    expect(legend).toContain("80% (q10–q90)");
    expect(legend).toContain("50% (q25–q75)");
    expect(legend).toContain("median (not a forecast)");
  });

  it("shows the fallback warning when fallback_used", async () => {
    (globalThis.fetch as ReturnType<typeof vi.fn>).mockResolvedValue({
      ok: true,
      json: async () => ({
        ...LATEST,
        forecast: { ...LATEST.forecast, fallback_used: true, params: null },
      }),
    });
    render(<DensityConePanel />);
    expect(
      await screen.findByText(/EWMA FALLBACK — GJR fit unavailable/),
    ).toBeTruthy();
  });

  it("opens on the 1-5 day fan and switches to the focused view", async () => {
    render(<DensityConePanel />);
    const chart = await screen.findByTestId("spx-density-chart");
    expect(chart.getAttribute("data-view")).toBe("fan");
    fireEvent.click(screen.getByRole("button", { name: /next session/i }));
    expect(
      screen.getByTestId("spx-density-chart").getAttribute("data-view"),
    ).toBe("focused");
  });

  it("stays quiet when every level is valid", async () => {
    render(<DensityConePanel />);
    await screen.findByTestId("spx-density-panel");
    // Notes are exception-only: with nothing dropped there is nothing to say.
    expect(screen.queryByTestId("cone-levels-note")).toBeNull();
  });

  it("discloses a dropped wall rather than hiding the gap", async () => {
    (globalThis.fetch as ReturnType<typeof vi.fn>).mockResolvedValue({
      ok: true,
      json: async () => ({
        ...LATEST,
        gamma_levels: {
          ...LATEST.gamma_levels,
          call_wall: null,
          source: "gex_snapshots",
          dropped: ["call_wall"],
        },
      }),
    });
    render(<DensityConePanel />);
    const note = await screen.findByTestId("cone-levels-note");
    expect(note.textContent).toContain("call_wall");
    expect(note.textContent).toContain("wrong side of spot");
  });

  it("counts close-only sessions instead of drawing invented candles", async () => {
    render(<DensityConePanel />);
    const note = await screen.findByTestId("cone-ohlc-note");
    expect(note.textContent).toMatch(/1 session close-only/);
  });
});
