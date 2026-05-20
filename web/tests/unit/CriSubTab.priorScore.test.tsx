/* @vitest-environment jsdom */
import { describe, expect, it } from "vitest";

import { priorComponentScore } from "@/components/regime/CriSubTab";
import type { CriHistoryEntry } from "@/components/regime/CriHistoryChart";

// Helper: build a partial entry; date is required but irrelevant for scoring.
const entry = (over: Partial<CriHistoryEntry>): CriHistoryEntry =>
  ({ date: "2026-05-20", vix: null, vvix: null, ...over }) as CriHistoryEntry;

describe("priorComponentScore (v3 calibration)", () => {
  // VIX: floor 13 (was 15), RoC denom 40 (was 60)
  it("VIX: applies new floor 13 and RoC denom 40", () => {
    // VIX=18, RoC=4.6 → lvl = (18-13)/27 * 15 = 2.78; roc = 4.6/40 * 10 = 1.15;
    // total = 3.93 → round1 = 3.9
    const score = priorComponentScore(
      entry({ vix: 18, vix_5d_roc: 4.6 }),
      "vix",
    );
    expect(score).toBeCloseTo(3.9, 1);
  });

  it("VIX: returns 0 at the new floor (13)", () => {
    const score = priorComponentScore(entry({ vix: 13, vix_5d_roc: 0 }), "vix");
    expect(score).toBe(0);
  });

  // VVIX: floor 80 (was 85)
  it("VVIX: applies new floor 80", () => {
    // VVIX=95, VIX=18, ratio=5.28; lvl = (95-80)/50 * 12 = 3.6;
    // ratio_sub = (5.28-5)/3 * 7 = 0.648; roc=0 → total = 4.248 → round1 = 4.2
    const score = priorComponentScore(
      entry({ vvix: 95, vix: 18, vvix_5d_roc: 0 }),
      "vvix",
    );
    expect(score).toBeCloseTo(4.2, 1);
  });

  // Correlation: unchanged (no v3 calibration delta)
  it("correlation: unchanged (no v3 delta)", () => {
    // cor1m=27, change=0 → lvl = (27-25)/45 * 17 = 0.756 → round1 = 0.8
    const score = priorComponentScore(
      entry({ cor1m: 27, cor1m_5d_change: 0 }),
      "correlation",
    );
    expect(score).toBeCloseTo(0.8, 1);
  });

  // Momentum: v3 structural-15 + tactical-10
  it("momentum: tactical alone fires when SPX above MA", () => {
    // Above MA (+6%) → structural=0; pullback -2% → tactical = 2/4 * 10 = 5.0
    const score = priorComponentScore(
      entry({ spx_vs_ma_pct: 6.0, pullback_20d_pct: -2.0 }),
      "momentum",
    );
    expect(score).toBeCloseTo(5.0, 1);
  });

  it("momentum: structural + tactical combine below MA", () => {
    // -5% below MA → structural = abs(-5)/10 * 15 = 7.5
    // -3% pullback → tactical = 3/4 * 10 = 7.5
    // total = 15.0 (no clip)
    const score = priorComponentScore(
      entry({ spx_vs_ma_pct: -5.0, pullback_20d_pct: -3.0 }),
      "momentum",
    );
    expect(score).toBeCloseTo(15.0, 1);
  });

  it("momentum: pre-v3 history (missing pullback_20d_pct) treats tactical as 0", () => {
    // Old rows from before the v3 history-entry change → tactical=0.
    // -5% below MA → structural = 7.5; tactical=0; total=7.5
    const score = priorComponentScore(
      entry({ spx_vs_ma_pct: -5.0 }),
      "momentum",
    );
    expect(score).toBeCloseTo(7.5, 1);
  });

  it("momentum: capped at 25", () => {
    const score = priorComponentScore(
      entry({ spx_vs_ma_pct: -20.0, pullback_20d_pct: -10.0 }),
      "momentum",
    );
    expect(score).toBe(25);
  });

  it("returns null when prior is undefined", () => {
    expect(priorComponentScore(undefined, "vix")).toBeNull();
  });
});
