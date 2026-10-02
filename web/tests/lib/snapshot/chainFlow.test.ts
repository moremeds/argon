// chainFlow extraction — oracle is the pre-move inline block from
// ChainFlowReadPanel.tsx. All three frozen fixtures ship an empty flow_table,
// so the fixture pass pins the empty path and literal rows cover the branches.
import { describe, expect, it } from "vitest";
import type { TradeInsightsResponse } from "@/lib/api";
import { chainFlowRead, type ChainFlowRow } from "@/lib/snapshot/chainFlow";
import aapl from "@/tests/fixtures/mcp/aapl_trade_insights.json";
import nvda from "@/tests/fixtures/mcp/nvda_trade_insights.json";
import spy from "@/tests/fixtures/mcp/spy_trade_insights.json";

const TI = {
  AAPL: aapl as unknown as TradeInsightsResponse,
  NVDA: nvda as unknown as TradeInsightsResponse,
  SPY: spy as unknown as TradeInsightsResponse,
};

const row = (over: Partial<ChainFlowRow>): ChainFlowRow => ({
  strike: "100",
  volume_oi_note: "",
  read: "",
  requires_t1_oi_confirmation: false,
  ...over,
});

describe("chainFlowRead on the frozen fixtures (empty flow_table)", () => {
  for (const [ticker, payload] of Object.entries(TI)) {
    it(`${ticker}: inconclusive read, no strongest, no highlights`, () => {
      const r = chainFlowRead(payload.flow_table);
      expect(r.totalCallVolume).toBe(0);
      expect(r.totalPutVolume).toBe(0);
      expect(r.tapeRatio).toBeNull();
      expect(r.t1Count).toBe(0);
      expect(r.strongest).toBeUndefined();
      expect(r.highlightedRows).toEqual([]);
      expect(r.flowRead).toBe(
        "Put volume is unavailable, so call/put balance is inconclusive.",
      );
      expect(r.activityRead).toBe(
        "No single strike stands out from the available rows.",
      );
      expect(r.confirmationRead).toBe(
        "No highlighted strikes need next-day OI confirmation.",
      );
    });
  }
});

describe("chainFlowRead branches (literal rows)", () => {
  it("call-heavy at ratio >= 1.2", () => {
    const r = chainFlowRead([
      row({ call_volume: 120, put_volume: 100 }),
      row({ call_volume: 6, put_volume: 0 }),
    ]);
    expect(r.tapeRatio).toBeCloseTo(126 / 100, 10);
    expect(r.flowRead).toBe(
      `Calls traded ${r.tapeRatio!.toFixed(2)}x puts across available rows, so flow leans call-heavy.`,
    );
  });

  it("put-heavy at ratio <= 0.8 and balanced between", () => {
    const putHeavy = chainFlowRead([row({ call_volume: 80, put_volume: 100 })]);
    expect(putHeavy.tapeRatio).toBe(0.8);
    expect(putHeavy.flowRead).toContain("put-heavy");
    const balanced = chainFlowRead([row({ call_volume: 95, put_volume: 100 })]);
    expect(balanced.tapeRatio).toBe(0.95);
    expect(balanced.flowRead).toBe(
      "Call and put volume are roughly balanced at 0.95x.",
    );
  });

  it("nulls coerce to 0; zero put volume → null ratio", () => {
    const r = chainFlowRead([
      row({ call_volume: 50, put_volume: null }),
      row({ call_volume: null }),
    ]);
    expect(r.totalCallVolume).toBe(50);
    expect(r.totalPutVolume).toBe(0);
    expect(r.tapeRatio).toBeNull();
  });

  it("busiest strike = max(call vol + put vol + call OI + put OI)", () => {
    const r = chainFlowRead([
      row({ strike: "100", call_volume: 500, put_volume: 400 }),
      row({ strike: "200", call_volume: 10, call_open_interest: 2000 }),
    ]);
    expect(r.strongest?.strike).toBe("200"); // OI counts, not just volume
    expect(r.activityRead).toBe(
      "The busiest strike is 200, which is the first place to inspect for pinning or crowding.",
    );
  });

  it("top-8 highlight ordering: volume first, t1 rows boosted +100000", () => {
    const rows = [
      row({ strike: "A", call_volume: 900 }),
      row({ strike: "B", call_volume: 5, requires_t1_oi_confirmation: true }),
      row({ strike: "C", put_volume: 50 }),
      ...Array.from({ length: 8 }, (_, i) =>
        row({ strike: `F${i}`, call_volume: 10 }),
      ),
    ];
    const r = chainFlowRead(rows);
    expect(r.highlightedRows).toHaveLength(8);
    expect(r.highlightedRows[0].strike).toBe("B"); // 5 + 100000 boost wins
    expect(r.highlightedRows[1].strike).toBe("A");
    expect(r.t1Count).toBe(1);
    expect(r.confirmationRead).toBe(
      "1 strike needs next-day OI confirmation before treating volume as new positioning.",
    );
  });

  it("pluralizes the confirmation read", () => {
    const r = chainFlowRead([
      row({ requires_t1_oi_confirmation: true }),
      row({ requires_t1_oi_confirmation: true }),
    ]);
    expect(r.t1Count).toBe(2);
    expect(r.confirmationRead).toContain("2 strikes need");
  });
});
