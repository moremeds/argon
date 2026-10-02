// Pure-function parity tests for web/lib/regime/derive/cri.ts on the frozen
// regime fixtures. The `oracle*` functions are verbatim copies of the inline
// expressions removed from components/regime/CriSubTab.tsx — including the
// priorComponentScore constants, which must keep matching
// src/uw_scan/cards/cri_scorers.py.
//
// No clock injection here: none of these derivations read Date.now().
import { describe, expect, it } from "vitest";
import criLiveFixture from "../../fixtures/mcp/regime_cri_live.json";
import criHistFixture from "../../fixtures/mcp/regime_cri_history.json";
import {
  criDailySeries,
  criPrevCloses,
  prevClose,
  priorComponentScore,
  priorHistoryRow,
  spxMedianFiltered,
  vixDelta3dSeries,
  vvixVixRatio,
} from "@/lib/regime/derive/cri";
import type { CriLiveResponse } from "@/lib/regime/useCriLive";
import type { CriDailyEntry } from "@/lib/regime/useCriSeries";
import type { CriHistoryEntry } from "@/components/regime/CriHistoryChart";
import type { ComponentSlot } from "@/components/regime/primitives/ComponentBar";

const live = criLiveFixture as unknown as CriLiveResponse;
const rows = criHistFixture.rows as unknown as CriDailyEntry[];
const history = (live.history ?? []) as unknown as CriHistoryEntry[];

/* ─── oracles: the original inline expressions, verbatim ─── */

function oraclePriorScore(
  prior: CriHistoryEntry | undefined,
  slot: ComponentSlot,
): number | null {
  if (!prior) return null;
  const clip = (x: number, lo: number, hi: number) =>
    Math.max(lo, Math.min(hi, x));
  const round1 = (x: number) => Math.round(x * 10) / 10;
  if (slot === "vix") {
    if (prior.vix == null || prior.vix_5d_roc == null) return null;
    const lvl = clip(((prior.vix - 13) / 27) * 15, 0, 15);
    const roc = clip((Math.max(prior.vix_5d_roc, 0) / 40) * 10, 0, 10);
    return round1(lvl + roc);
  }
  if (slot === "vvix") {
    if (prior.vvix == null || prior.vix == null || prior.vix <= 0) return null;
    const ratio = prior.vvix / prior.vix;
    const lvl = clip(((prior.vvix - 80) / 50) * 12, 0, 12);
    const r = clip(((ratio - 5) / 3) * 7, 0, 7);
    const rocRaw = prior.vvix_5d_roc ?? 0;
    const roc = clip((Math.max(rocRaw, 0) / 25) * 6, 0, 6);
    return round1(lvl + r + roc);
  }
  if (slot === "correlation") {
    if (prior.cor1m == null) return null;
    const lvl = clip(((prior.cor1m - 25) / 45) * 17, 0, 17);
    const chg = prior.cor1m_5d_change ?? 0;
    const spike = clip((Math.max(chg, 0) / 20) * 8, 0, 8);
    return round1(lvl + spike);
  }
  if (slot === "momentum") {
    if (prior.spx_vs_ma_pct == null) return null;
    const d = prior.spx_vs_ma_pct;
    const structural = d >= 0 ? 0 : clip((Math.abs(d) / 10) * 15, 0, 15);
    const pullback = prior.pullback_20d_pct ?? 0;
    const tactical =
      pullback >= 0 ? 0 : clip((Math.abs(pullback) / 4) * 10, 0, 10);
    return round1(clip(structural + tactical, 0, 25));
  }
  return null;
}

function oraclePrevClose(
  h: CriHistoryEntry[] | undefined,
  key: keyof CriHistoryEntry,
): number | null {
  if (!h || h.length < 2) return null;
  const v = h[h.length - 2][key];
  return typeof v === "number" && Number.isFinite(v) ? v : null;
}

function oracleDseries(
  dailyRows: CriDailyEntry[],
  k: keyof CriDailyEntry,
): (number | null)[] {
  return dailyRows.map((r) => {
    const v = r[k];
    return typeof v === "number" && Number.isFinite(v) ? v : null;
  });
}

describe("priorHistoryRow + priorComponentScore", () => {
  it("prior row is the second-to-last history entry", () => {
    expect(priorHistoryRow(live)).toEqual(history[history.length - 2]);
    expect(priorHistoryRow(live)?.date).toBe("2026-09-17");
  });

  it("scores match the verbatim oracle for every slot", () => {
    const prior = priorHistoryRow(live);
    for (const slot of [
      "vix",
      "vvix",
      "correlation",
      "momentum",
    ] as ComponentSlot[]) {
      expect(priorComponentScore(prior, slot)).toBe(
        oraclePriorScore(prior, slot),
      );
    }
  });

  it("anchors on the 2026-09-17 prior row", () => {
    const prior = priorHistoryRow(live);
    expect(priorComponentScore(prior, "vix")).toBe(1.4);
    expect(priorComponentScore(prior, "vvix")).toBe(3.4);
    expect(priorComponentScore(prior, "correlation")).toBe(0);
    expect(priorComponentScore(prior, "momentum")).toBe(3.6);
  });

  it("undefined prior → null", () => {
    for (const slot of [
      "vix",
      "vvix",
      "correlation",
      "momentum",
    ] as ComponentSlot[]) {
      expect(priorComponentScore(undefined, slot)).toBeNull();
    }
  });
});

describe("criPrevCloses + prevClose", () => {
  it("anchors on the fixture's 20-row history", () => {
    expect(criPrevCloses(live)).toEqual({
      vixClose: 15.44,
      vvixClose: 87.72,
      spyClose: 7637.76,
      cor1mPrevClose: 9.23,
    });
  });

  it("cor1m_previous_close payload field wins over the history row", () => {
    // history[-2].cor1m = 10.79; the payload scalar 9.23 takes precedence.
    const r = criPrevCloses(live);
    expect(r.cor1mPrevClose).toBe(9.23);
    expect(history[history.length - 2].cor1m).toBe(10.79);
    const noField = { ...live, cor1m_previous_close: null };
    expect(criPrevCloses(noField as CriLiveResponse).cor1mPrevClose).toBe(10.79);
  });

  it("prevClose oracles", () => {
    for (const key of ["vix", "vvix", "spy", "cor1m"] as const) {
      expect(prevClose(history, key)).toBe(oraclePrevClose(history, key));
    }
    expect(prevClose([], "vix")).toBeNull();
    expect(prevClose([history[0]], "vix")).toBeNull();
  });
});

describe("vvixVixRatio", () => {
  it("payload scalar wins when present", () => {
    expect(vvixVixRatio(live)).toBe(5.9);
  });

  it("falls back to vvix/vix when the scalar is absent", () => {
    const d = {
      ...live,
      vvix_vix_ratio: null,
      vix: 14.81,
      vvix: 87.38,
    } as unknown as CriLiveResponse;
    expect(vvixVixRatio(d)).toBeCloseTo(87.38 / 14.81, 12);
    const zeroVix = { ...d, vix: 0 } as CriLiveResponse;
    expect(vvixVixRatio(zeroVix)).toBeNull();
  });
});

describe("criDailySeries / vixDelta3dSeries / spxMedianFiltered", () => {
  it("criDailySeries projects one key with non-finite → null", () => {
    expect(criDailySeries(rows, "vix")).toEqual(oracleDseries(rows, "vix"));
    expect(criDailySeries(rows, "vix")).toHaveLength(90);
    expect(criDailySeries(rows, "vix")[89]).toBe(14.81);
  });

  it("vixDelta3dSeries = vix[i] − vix[i−3], verbatim oracle", () => {
    const vixDaily = oracleDseries(rows, "vix");
    const oracle = vixDaily.map((v, i) => {
      const base = i >= 3 ? vixDaily[i - 3] : null;
      return v != null && base != null ? v - base : null;
    });
    const r = vixDelta3dSeries(rows);
    expect(r).toEqual(oracle);
    expect(r.slice(0, 3)).toEqual([null, null, null]);
    expect(r[r.length - 1]).toBeCloseTo(-2.39, 10);
  });

  it("spxMedianFiltered nulls points outside [median/2, 2·median]", () => {
    const raw = oracleDseries(rows, "spx");
    const sorted = raw
      .filter((v): v is number => v != null)
      .sort((a, b) => a - b);
    const median = sorted.length
      ? sorted[Math.floor(sorted.length / 2)]
      : null;
    const oracle =
      median == null
        ? raw
        : raw.map((v) =>
            v != null && (v < median / 2 || v > median * 2) ? null : v,
          );
    const r = spxMedianFiltered(rows);
    expect(r.median).toBeCloseTo(7543.59, 8);
    expect(r.series).toEqual(oracle);
    expect(r.series.filter((v) => v == null)).toHaveLength(1);
    expect(r.series[r.series.length - 1]).toBe(7650.5);
  });

  it("all-null input → median null, raw series pass-through", () => {
    const empty: CriDailyEntry[] = [
      { date: "2026-01-01" } as CriDailyEntry,
      { date: "2026-01-02" } as CriDailyEntry,
    ];
    const r = spxMedianFiltered(empty);
    expect(r.median).toBeNull();
    expect(r.series).toEqual([null, null]);
  });
});
