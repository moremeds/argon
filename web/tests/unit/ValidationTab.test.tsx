/* @vitest-environment jsdom */
import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import ValidationTab from "@/components/regime/ValidationTab";

const FAKE = {
  backtest_md: "# CRI Backtest\nMean: 8.5",
  backtest_csv_rows: 124,
  oos: {
    as_of: "2026-05-19",
    notebook: "...",
    method: "walk-forward",
    labels: [],
    scores: [
      { model: "CRI v2", auc_dd5: 0.621, auc_vix30: null, auc_dd10: null },
      {
        model: "Naive VIX p80",
        auc_dd5: 0.637,
        auc_vix30: null,
        auc_dd10: null,
      },
    ],
    interpretation: "VIX alone captures most of the signal.",
  },
};

beforeEach(() => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => ({ ok: true, json: async () => FAKE })),
  );
});

afterEach(() => vi.unstubAllGlobals());

describe("ValidationTab", () => {
  it("renders the backtest md + OOS table", async () => {
    render(<ValidationTab />);
    // After the CriValidationPanel lift, validation-tab is the outer shell
    // and renders immediately. Wait for the lifted panel's content instead —
    // that's the real post-fetch race-gate.
    await waitFor(() =>
      expect(screen.queryByText("WARM-STORE BACKTEST")).not.toBeNull(),
    );
    expect(screen.getByTestId("validation-tab")).not.toBeNull();
    expect(screen.getByTestId("oos-block")).not.toBeNull();
    expect(screen.getByText("CRI v2")).not.toBeNull();
    expect(screen.getByText("0.621")).not.toBeNull();
  });
});
