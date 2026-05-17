/* @vitest-environment jsdom */
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

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

  it("renders score and level for populated data", () => {
    render(<CriSubTabView data={POPULATED} />);
    expect(screen.getByTestId("cri-score").textContent).toContain("33.4");
    expect(screen.getByTestId("cri-level").textContent).toBe("ELEVATED");
  });

  it("renders the four component bars", () => {
    render(<CriSubTabView data={POPULATED} />);
    expect(screen.getByText(/component scores/i)).not.toBeNull();
    expect(screen.getByText("VIX")).not.toBeNull();
    expect(screen.getByText("VVIX")).not.toBeNull();
    expect(screen.getByText("COR1M")).not.toBeNull();
    expect(screen.getByText("SPX MOM")).not.toBeNull();
  });

  it("renders SILENT crash trigger when not fired", () => {
    render(<CriSubTabView data={POPULATED} />);
    expect(screen.getByTestId("crash-trigger-state").textContent).toBe(
      "SILENT",
    );
  });

  it("renders FIRED crash trigger when triggered", () => {
    render(<CriSubTabView data={FIRED_TRIGGER} />);
    expect(screen.getByTestId("crash-trigger-state").textContent).toBe("FIRED");
  });

  it("renders mini history chart when history rows exist", () => {
    render(<CriSubTabView data={POPULATED} />);
    expect(screen.getByTestId("cri-mini-history")).not.toBeNull();
  });

  it("renders CTA exposure card", () => {
    render(<CriSubTabView data={POPULATED} />);
    expect(screen.getByText(/cta vol-target model/i)).not.toBeNull();
    // 70.4 → fmtDecimal(_, 0) → "70%"
    expect(screen.getByText("70%")).not.toBeNull();
  });
});
