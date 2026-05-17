/* @vitest-environment jsdom */
import { render, screen } from "@testing-library/react";
import { describe, expect, it, beforeEach, afterEach, vi } from "vitest";

import { CriSubTabView } from "@/components/regime/CriSubTab";
import type { CriResponse } from "@/lib/regime/useCri";

const POPULATED: CriResponse = {
  status: "ok",
  scan_time: "2026-05-15T20:30:00+00:00",
  date: "2026-05-15",
  vix: 18.43,
  vvix: 92.9,
  spy: 588.12,
  cor1m: 10.8,
  spx_distance_pct: -2.5,
  realized_vol: 14.2,
  vix_5d_roc: 2.5,
  vvix_vix_ratio: 5.04,
  spx_100d_ma: 605.0,
  cor1m_previous_close: 10.5,
  cor1m_5d_change: 0.6,
  cri: {
    score: 33.4,
    level: "ELEVATED",
    components: { vix: 8.0, vvix: 12.0, correlation: 6.4, momentum: 7.0 },
  },
  cta: {
    realized_vol: 14.2,
    exposure_pct: 70.4,
    forced_reduction_pct: 29.6,
    forced_reduction: true,
    est_selling_bn: 103.6,
    selling_usd_b: 103.6,
  },
  crash_trigger: {
    fired: false,
    triggered: false,
    conditions: {
      spx_below_100d_ma: true,
      realized_vol_gt_25: false,
      cor1m_gt_60: false,
    },
    values: { realized_vol: 14.2, cor1m: 10.8 },
  },
  history: [
    {
      date: "2026-05-13",
      vix: 17.8,
      vvix: 91.0,
      spy: 585.0,
      cor1m: 10.2,
      realized_vol: 13.9,
      spx_vs_ma_pct: -2.1,
      vix_5d_roc: 2.5,
    },
    {
      date: "2026-05-14",
      vix: 18.1,
      vvix: 92.2,
      spy: 586.3,
      cor1m: 10.5,
      realized_vol: 14.0,
      spx_vs_ma_pct: -2.3,
      vix_5d_roc: 3.0,
    },
  ],
  spy_closes: [],
};

const FIRED_TRIGGER: CriResponse = {
  ...POPULATED,
  cri: {
    score: 82.0,
    level: "CRITICAL",
    components: { vix: 22.0, vvix: 20.0, correlation: 20.0, momentum: 20.0 },
  },
  crash_trigger: {
    fired: true,
    triggered: true,
    conditions: {
      spx_below_100d_ma: true,
      realized_vol_gt_25: true,
      cor1m_gt_60: true,
    },
    values: { realized_vol: 30.0, cor1m: 70.0 },
  },
};

// jsdom doesn't have ResizeObserver — stub one so CriHistoryChart can mount.
beforeEach(() => {
  vi.stubGlobal(
    "ResizeObserver",
    class {
      observe() {}
      unobserve() {}
      disconnect() {}
    },
  );
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("CriSubTabView", () => {
  it("renders empty placeholder when data is null", () => {
    render(<CriSubTabView data={null} />);
    expect(screen.getByTestId("cri-empty-state")).not.toBeNull();
  });

  it("renders empty placeholder when status is empty", () => {
    render(
      <CriSubTabView
        data={{ ...POPULATED, status: "empty", cri: undefined }}
      />,
    );
    expect(screen.getByTestId("cri-empty-state")).not.toBeNull();
  });

  it("renders hero score (no decimals) and level badge", () => {
    render(<CriSubTabView data={POPULATED} />);
    // 33.4 → .toFixed(0) → "33"
    expect(screen.getByTestId("cri-score").textContent).toBe("33");
    expect(screen.getByTestId("cri-level").textContent).toBe("ELEVATED");
  });

  it("renders all four component bars (VIX/VVIX/CORRELATION/MOMENTUM)", () => {
    render(<CriSubTabView data={POPULATED} />);
    expect(screen.getByText("CRI COMPONENTS")).not.toBeNull();
    // Each component label is rendered inside the bar
    expect(screen.getAllByText("VIX").length).toBeGreaterThan(0);
    expect(screen.getAllByText("VVIX").length).toBeGreaterThan(0);
    expect(screen.getByText("CORRELATION")).not.toBeNull();
    expect(screen.getByText("MOMENTUM")).not.toBeNull();
  });

  it("renders INACTIVE crash trigger when not triggered", () => {
    render(<CriSubTabView data={POPULATED} />);
    expect(screen.getByTestId("crash-trigger-state").textContent).toBe(
      "INACTIVE",
    );
  });

  it("renders TRIGGERED crash trigger when all three conditions fire", () => {
    render(<CriSubTabView data={FIRED_TRIGGER} />);
    expect(screen.getByTestId("crash-trigger-state").textContent).toBe(
      "TRIGGERED",
    );
  });

  it("renders the 5-cell ticker strip", () => {
    render(<CriSubTabView data={POPULATED} />);
    expect(screen.getByTestId("strip-vix")).not.toBeNull();
    expect(screen.getByTestId("strip-vvix")).not.toBeNull();
    expect(screen.getByTestId("strip-spy")).not.toBeNull();
    expect(screen.getByTestId("strip-rvol")).not.toBeNull();
    expect(screen.getByTestId("strip-cor1m")).not.toBeNull();
  });

  it("renders the side-by-side 20-session history grid", () => {
    render(<CriSubTabView data={POPULATED} />);
    expect(screen.getByTestId("regime-history-grid")).not.toBeNull();
    expect(screen.getByTestId("regime-history-chart-vix-vvix")).not.toBeNull();
    expect(
      screen.getByTestId("regime-history-chart-rvol-cor1m"),
    ).not.toBeNull();
  });
});
