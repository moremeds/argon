/* @vitest-environment jsdom */
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import {
  afterEach,
  beforeEach,
  describe,
  expect,
  it,
  vi,
  type Mock,
} from "vitest";

import ValidationTab from "@/components/regime/ValidationTab";

const CRI_OK = {
  backtest_md: "# CRI Backtest\nMean: 8.5",
  backtest_csv_rows: 124,
  oos: {
    as_of: "2026-05-25",
    notebook: "scripts/backtest_cri.py",
    method: "walk-forward",
    labels: [],
    scores: [
      { model: "CRI v3", auc_dd5: 0.634, auc_vix30: null, auc_dd10: 0.633 },
    ],
    interpretation: "OK.",
  },
};

const VCG_OK = {
  backtest_md: "# VCG Backtest\n",
  n_days: 4708,
  composite_version: "1",
  credit_proxy: "HYG",
  interpretation_distribution: [
    { interpretation: "NORMAL", n: 2160, pct: 45.9 },
  ],
  named_crash_window: [],
};

let fetchMock: Mock;

beforeEach(() => {
  fetchMock = vi.fn();
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("ValidationTab switcher", () => {
  it("switches CRI -> VCG -> CRI; shows API detail on 503; clears stale error on switch back", async () => {
    fetchMock.mockImplementation((url: string) => {
      const u = String(url);
      if (u.endsWith("/regime/validation")) {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: async () => CRI_OK,
        });
      }
      if (u.endsWith("/regime/vcg-validation")) {
        return Promise.resolve({
          ok: false,
          status: 503,
          json: async () => ({
            detail:
              "no completed VCG backtest run at the current COMPOSITE_VERSION; run scripts/backtest_vcg.py to seed uw_scan.regime_backtest_runs",
          }),
        });
      }
      return Promise.resolve({
        ok: false,
        status: 500,
        json: async () => ({ detail: "unexpected url" }),
      });
    });

    render(<ValidationTab />);

    // Initial CRI render
    await waitFor(() =>
      expect(screen.queryByText("WARM-STORE BACKTEST")).not.toBeNull(),
    );

    // Switch to VCG → 503 with API detail message surfaced
    fireEvent.click(screen.getByTestId("validation-sub-vcg"));
    await waitFor(() => {
      const err = screen.queryByTestId("validation-error");
      expect(err).not.toBeNull();
      expect(err?.textContent).toContain("scripts/backtest_vcg.py");
    });

    // Switch back to CRI → stale error clears, CRI panel returns
    fireEvent.click(screen.getByTestId("validation-sub-cri"));
    await waitFor(() => {
      expect(screen.queryByTestId("validation-error")).toBeNull();
      expect(screen.queryByText("WARM-STORE BACKTEST")).not.toBeNull();
    });

    // 3 fetches: initial CRI, VCG, second CRI (component unmount path not exercised)
    expect(fetchMock).toHaveBeenCalledTimes(3);
  });

  it("renders VCG panel on happy path", async () => {
    fetchMock.mockImplementation((url: string) => {
      if (String(url).endsWith("/regime/vcg-validation")) {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: async () => VCG_OK,
        });
      }
      return Promise.resolve({
        ok: true,
        status: 200,
        json: async () => CRI_OK,
      });
    });

    render(<ValidationTab />);
    await waitFor(() =>
      expect(screen.queryByText("WARM-STORE BACKTEST")).not.toBeNull(),
    );
    fireEvent.click(screen.getByTestId("validation-sub-vcg"));
    await waitFor(() =>
      expect(screen.queryByText(/VCG BACKTEST \(HYG\)/)).not.toBeNull(),
    );
  });
});
