// flowTimeline had NO prior tests — the oracle is the pre-move map block from
// FlowTab.tsx TimelineSection, pinned on all three frozen *_stock.json
// payloads plus literal rows for the null/zero-denominator branches.
import { describe, expect, it } from "vitest";
import type { components } from "@/lib/types";
import { flowTimelineSeries } from "@/lib/snapshot/flowTimeline";
import aapl from "@/tests/fixtures/mcp/aapl_stock.json";
import nvda from "@/tests/fixtures/mcp/nvda_stock.json";
import spy from "@/tests/fixtures/mcp/spy_stock.json";

type Row = components["schemas"]["OptionsDailyRow"];
type Report = components["schemas"]["SingleStockReport"];

const STOCK = {
  AAPL: aapl as unknown as Report,
  NVDA: nvda as unknown as Report,
  SPY: spy as unknown as Report,
};

// Pre-move oracle: verbatim from FlowTab.
function oracle(timeline: Row[]) {
  return {
    dates: timeline.map((r) => r.date),
    totalVol: timeline.map((r) =>
      r.call_volume == null || r.put_volume == null
        ? null
        : r.call_volume + r.put_volume,
    ),
    pcVol: timeline.map((r) =>
      r.call_volume != null && r.call_volume !== 0 && r.put_volume != null
        ? r.put_volume / r.call_volume
        : null,
    ),
    totalOi: timeline.map((r) =>
      r.call_open_interest == null || r.put_open_interest == null
        ? null
        : r.call_open_interest + r.put_open_interest,
    ),
    pcOi: timeline.map((r) =>
      r.call_open_interest != null &&
      r.call_open_interest !== 0 &&
      r.put_open_interest != null
        ? r.put_open_interest / r.call_open_interest
        : null,
    ),
  };
}

describe("flowTimelineSeries on frozen stock payloads", () => {
  it.each(Object.entries(STOCK))("%s equals the pre-move oracle", (_t, rep) => {
    const out = flowTimelineSeries(rep.options_timeline!);
    expect(out).toEqual(oracle(rep.options_timeline!));
    expect(out.dates).toHaveLength(116);
  });

  it("pins the last bar's literals", () => {
    const a = flowTimelineSeries(STOCK.AAPL.options_timeline!);
    expect(a.dates.at(-1)).toBe("2026-09-18");
    expect(a.totalVol.at(-1)).toBe(1522957);
    expect(a.pcVol.at(-1)).toBeCloseTo(0.6209481803464861, 12);
    expect(a.totalOi.at(-1)).toBe(5370031);
    expect(a.pcOi.at(-1)).toBeCloseTo(0.777450865517586, 12);

    const s = flowTimelineSeries(STOCK.SPY.options_timeline!);
    expect(s.pcVol.at(-1)).toBeCloseTo(1.113216311175369, 12);
    expect(s.pcOi.at(-1)).toBeCloseTo(2.5443435507891685, 12);
  });
});

describe("flowTimelineSeries edge branches", () => {
  it("call_volume 0 or null → pcVol null; a real put_volume of 0 stays 0", () => {
    const out = flowTimelineSeries([
      { date: "2026-01-01", call_volume: 0, put_volume: 10 },
      { date: "2026-01-02", call_volume: 10, put_volume: 0 },
      { date: "2026-01-03", call_volume: null, put_volume: 5 },
      { date: "2026-01-04", call_volume: 10, put_volume: null },
    ]);
    expect(out.pcVol).toEqual([null, 0, null, null]);
    expect(out.totalVol).toEqual([10, 10, null, null]);
  });

  it("OI mirrors the same null/zero rules", () => {
    const out = flowTimelineSeries([
      { date: "d", call_open_interest: 0, put_open_interest: 5 },
      { date: "d2", call_open_interest: 5, put_open_interest: 0 },
      { date: "d3", call_open_interest: null, put_open_interest: 5 },
    ]);
    expect(out.pcOi).toEqual([null, 0, null]);
    expect(out.totalOi).toEqual([5, 5, null]);
  });

  it("empty input → empty series", () => {
    expect(flowTimelineSeries([])).toEqual({
      dates: [],
      totalVol: [],
      pcVol: [],
      totalOi: [],
      pcOi: [],
    });
  });
});
