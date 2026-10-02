// termMove — oracle is the pre-move sort/label block from TermMovePanel.tsx,
// pinned on the frozen trade-insights payloads plus literal branch cases.
import { describe, expect, it } from "vitest";
import type { TradeInsightsResponse } from "@/lib/api";
import { termMoveRead, type TermRow } from "@/lib/snapshot/termMove";
import aapl from "@/tests/fixtures/mcp/aapl_trade_insights.json";
import nvda from "@/tests/fixtures/mcp/nvda_trade_insights.json";
import spy from "@/tests/fixtures/mcp/spy_trade_insights.json";

const TI = {
  AAPL: aapl as unknown as TradeInsightsResponse,
  NVDA: nvda as unknown as TradeInsightsResponse,
  SPY: spy as unknown as TradeInsightsResponse,
};

const n = (v: string | number | null | undefined) =>
  v == null ? null : Number(v);

// Pre-move oracle: verbatim from TermMovePanel.
function oracle(rows: TermRow[]) {
  const byExpiry = [...rows].sort((a, b) => {
    const aDte = a.dte ?? 9999;
    const bDte = b.dte ?? 9999;
    return aDte - bDte;
  });
  const front = byExpiry[0];
  const back = byExpiry.find((row) => row.expiry !== front?.expiry) ?? null;
  const highestDaily = [...rows].sort(
    (a, b) =>
      (n(b.daily_implied_move_perc) ?? -1) -
      (n(a.daily_implied_move_perc) ?? -1),
  )[0];
  const frontDaily = front ? n(front.daily_implied_move_perc) : null;
  const backDaily = back ? n(back.daily_implied_move_perc) : null;
  const curveRead =
    frontDaily != null && backDaily != null && frontDaily > backDaily
      ? "Front elevated"
      : frontDaily != null && backDaily != null && frontDaily < backDaily
        ? "Back elevated"
        : "Flat / unclear";
  const highlightedCount = Math.min(rows.length, 6);
  const highlightedRows = byExpiry.slice(0, highlightedCount);
  return {
    byExpiry,
    front,
    back,
    highestDaily,
    frontDaily,
    backDaily,
    curveRead,
    highlightedCount,
    highlightedRows,
  };
}

const row = (over: Partial<TermRow>): TermRow => ({
  expiry: "2099-01-01",
  read: "",
  ...over,
});

describe("termMoveRead on frozen trade-insights payloads", () => {
  it.each(Object.entries(TI))("%s equals the pre-move oracle", (_t, p) => {
    const rows = p.term_structure_table;
    expect(termMoveRead(rows)).toEqual(oracle(rows));
  });

  it("pins AAPL literals", () => {
    const r = termMoveRead(TI.AAPL.term_structure_table);
    expect(r.front?.expiry).toBe("2026-09-18");
    expect(r.front?.dte).toBe(0);
    expect(r.back?.expiry).toBe("2026-09-21");
    expect(r.curveRead).toBe("Flat / unclear");
    expect(r.highestDaily?.expiry).toBe("2026-09-21");
    expect(n(r.highestDaily?.daily_implied_move_perc)).toBeCloseTo(
      0.0034302075840196367,
      12,
    );
    expect(r.highlightedCount).toBe(6);
    expect(r.highlightedRows).toHaveLength(6);
  });

  it("pins SPY literals", () => {
    const r = termMoveRead(TI.SPY.term_structure_table);
    expect(r.front?.expiry).toBe("2026-09-18");
    expect(r.back?.expiry).toBe("2026-09-21");
    expect(r.highestDaily?.expiry).toBe("2026-09-22");
    expect(n(r.highestDaily?.daily_implied_move_perc)).toBeCloseTo(
      0.00142245038806969,
      12,
    );
  });
});

describe("termMoveRead edge branches", () => {
  it("front > back daily → 'Front elevated'; reverse → 'Back elevated'", () => {
    const elevated = termMoveRead([
      row({ expiry: "2026-01-01", dte: 1, daily_implied_move_perc: "0.05" }),
      row({ expiry: "2026-01-08", dte: 8, daily_implied_move_perc: "0.02" }),
    ]);
    expect(elevated.curveRead).toBe("Front elevated");
    const backElevated = termMoveRead([
      row({ expiry: "2026-01-01", dte: 1, daily_implied_move_perc: "0.02" }),
      row({ expiry: "2026-01-08", dte: 8, daily_implied_move_perc: "0.05" }),
    ]);
    expect(backElevated.curveRead).toBe("Back elevated");
  });

  it("equal dailies or a missing back → 'Flat / unclear'", () => {
    const flat = termMoveRead([
      row({ expiry: "2026-01-01", dte: 1, daily_implied_move_perc: "0.03" }),
      row({ expiry: "2026-01-08", dte: 8, daily_implied_move_perc: "0.03" }),
    ]);
    expect(flat.curveRead).toBe("Flat / unclear");
    const single = termMoveRead([
      row({ expiry: "2026-01-01", dte: 1, daily_implied_move_perc: "0.03" }),
    ]);
    expect(single.back).toBeNull();
    expect(single.curveRead).toBe("Flat / unclear");
  });

  it("null dte sorts last (as 9999); empty input is honest", () => {
    const r = termMoveRead([
      row({ expiry: "2099-12-31", dte: null }),
      row({ expiry: "2026-01-01", dte: 5 }),
    ]);
    expect(r.front?.expiry).toBe("2026-01-01");
    const empty = termMoveRead([]);
    expect(empty.front).toBeUndefined();
    expect(empty.back).toBeNull();
    expect(empty.highestDaily).toBeUndefined();
    expect(empty.curveRead).toBe("Flat / unclear");
    expect(empty.highlightedRows).toEqual([]);
  });
});
