/* @vitest-environment jsdom */
import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import DensityConePanel from "@/components/regime/DensityConePanel";

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
    { date: "2026-07-29", close: 7316.15 },
    { date: "2026-07-30", close: 7437.63 },
  ],
  disclaimer: "Display-only",
};

beforeEach(() => {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue({ ok: true, json: async () => LATEST }),
  );
});

describe("DensityConePanel", () => {
  it("renders the display-only chip and the honesty copy", async () => {
    render(<DensityConePanel />);
    expect(
      await screen.findByText(/DISPLAY ONLY · NOT A TRADING SIGNAL/),
    ).toBeTruthy();
    expect(await screen.findByText(/p50 is not a direction call/)).toBeTruthy();
    expect(screen.getByTestId("spx-density-panel")).toBeTruthy();
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
});
