/* @vitest-environment jsdom */
import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import VcgStressHistorySection from "@/components/regime/vcg/VcgStressHistorySection";

const FIXTURE = {
  backtest_md: "",
  n_days: 4710,
  composite_version: "2",
  credit_proxy: "HY_OAS",
  interpretation_distribution: [],
  named_crash_window: [],
  stress_history: [],
  stress_history_summary: {
    by_interpretation: [
      {
        interpretation: "PANIC",
        n: 83,
        mean_fwd_5d_pct: 0.2,
        mean_fwd_20d_pct: 2.88,
        mean_fwd_60d_pct: 2.29,
        winrate_20d_pct: 53.0,
        winrate_60d_pct: 41.0,
      },
      {
        interpretation: "RISK_OFF",
        n: 133,
        mean_fwd_5d_pct: 0.2,
        mean_fwd_20d_pct: 0.15,
        mean_fwd_60d_pct: 3.04,
        winrate_20d_pct: 67.7,
        winrate_60d_pct: 74.4,
      },
    ],
  },
};

beforeEach(() => {
  globalThis.fetch = vi.fn().mockResolvedValue({
    ok: true,
    json: async () => FIXTURE,
  } as Response);
});

describe("VcgStressHistorySection summary line", () => {
  it("renders aggregate stats for PANIC and RISK_OFF", async () => {
    render(<VcgStressHistorySection />);
    await waitFor(() => {
      expect(screen.getByTestId("vcg-stress-summary")).toBeDefined();
    });
    const summary = screen.getByTestId("vcg-stress-summary");
    expect(summary.textContent).toMatch(/83 historical PANIC/);
    expect(summary.textContent).toMatch(/\+2\.88/);
    expect(summary.textContent).toMatch(/133 historical RISK_OFF/);
    expect(summary.textContent).toMatch(/\+3\.04/);
  });
});
