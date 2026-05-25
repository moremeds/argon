/* @vitest-environment jsdom */
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import VcgValidationPanel from "@/components/regime/VcgValidationPanel";

describe("VcgValidationPanel", () => {
  it("renders the credit proxy + distribution rows", () => {
    const { container } = render(
      <VcgValidationPanel
        data={
          {
            backtest_md: "# VCG Backtest\n",
            n_days: 100,
            composite_version: "1",
            credit_proxy: "HYG",
            interpretation_distribution: [
              { interpretation: "NORMAL", n: 60, pct: 60.0 },
              { interpretation: "SUPPRESSED", n: 40, pct: 40.0 },
            ],
            named_crash_window: [],
          } as unknown as Parameters<typeof VcgValidationPanel>[0]["data"]
        }
      />,
    );
    expect(screen.queryByText(/VCG BACKTEST \(HYG\)/)).not.toBeNull();
    expect(screen.queryByText("NORMAL")).not.toBeNull();
    expect(screen.queryByText("SUPPRESSED")).not.toBeNull();
    expect(
      container.querySelector('[data-testid="vcg-validation-panel"]'),
    ).not.toBeNull();
  });

  it("renders one sub-table per named-crash event with 7 offset rows", () => {
    const offsets = [-5, -3, -1, 0, 1, 3, 5].map((off) => ({
      offset_days: off,
      vcg: -0.5,
      vcg_adj: -0.5,
      beta1: -0.02,
      beta2: -0.04,
      sign_ok: true,
      interpretation: "NORMAL",
    }));
    const { container } = render(
      <VcgValidationPanel
        data={
          {
            backtest_md: "# VCG Backtest\n",
            n_days: 4708,
            composite_version: "1",
            credit_proxy: "HYG",
            interpretation_distribution: [
              { interpretation: "NORMAL", n: 1, pct: 100.0 },
            ],
            named_crash_window: [
              {
                date: "2008-09-15",
                label: "Lehman bankruptcy",
                offsets,
              },
            ],
          } as unknown as Parameters<typeof VcgValidationPanel>[0]["data"]
        }
      />,
    );
    expect(screen.queryByText(/Lehman bankruptcy/)).not.toBeNull();
    // 1 row in distribution table + 7 rows in named-crash sub-table = 8 total
    const rows = container.querySelectorAll("tbody tr");
    expect(rows.length).toBe(8);
    // Offset formatting: positive offsets get a `+` prefix
    expect(screen.queryByText("+1")).not.toBeNull();
    expect(screen.queryByText("+3")).not.toBeNull();
    expect(screen.queryByText("-5")).not.toBeNull();
  });

  it("shows placeholder when no crash window data is available", () => {
    render(
      <VcgValidationPanel
        data={
          {
            backtest_md: "# VCG Backtest\n",
            n_days: 5,
            composite_version: "1",
            credit_proxy: "HYG",
            interpretation_distribution: [],
            named_crash_window: [],
          } as unknown as Parameters<typeof VcgValidationPanel>[0]["data"]
        }
      />,
    );
    expect(
      screen.queryByText(/No named-crash window data persisted/),
    ).not.toBeNull();
  });
});
