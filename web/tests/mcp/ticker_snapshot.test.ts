// ticker_snapshot — stub ToolCtx serves the frozen fixtures; the assertions
// pin section shape, the SPX/SPY/QQQ/IWM cockpit gate, per-section error
// isolation, fetch sharing (one /stock GET, one /trade-insights/preview GET), and
// value parity with the lib functions the UI now calls.
import { describe, expect, it, vi } from "vitest";
import { z } from "zod";
import type { ToolCtx } from "@/mcp/types";
import type {
  CockpitDealerResponse,
  CockpitStateResponse,
  CockpitVrpResponse,
  SingleStockReport,
  TradeInsightsResponse,
  TechnicalsResponse,
  TechnicalsLiveResponse,
  MagnetsResponse,
} from "@/lib/api";
import { chainFlowRead } from "@/lib/snapshot/chainFlow";
import { termMoveRead } from "@/lib/snapshot/termMove";
import { flowTimelineSeries } from "@/lib/snapshot/flowTimeline";
import { gammaBarTiles } from "@/lib/snapshot/gammaBar";
import { netExposureCurve } from "@/lib/snapshot/greeksNet";
import { vrpStats } from "@/lib/snapshot/cockpitVrp";
import { groupByExpiry, totals, peaks } from "@/lib/snapshot/cockpitDealer";
import aaplT from "@/tests/fixtures/mcp/aapl_technicals.json";
import aaplLive from "@/tests/fixtures/mcp/aapl_technicals_live.json";
import aaplM from "@/tests/fixtures/mcp/aapl_magnets.json";
import aaplS from "@/tests/fixtures/mcp/aapl_stock.json";
import aaplTi from "@/tests/fixtures/mcp/aapl_trade_insights.json";
import spyT from "@/tests/fixtures/mcp/spy_technicals.json";
import spyLive from "@/tests/fixtures/mcp/spy_technicals_live.json";
import spyM from "@/tests/fixtures/mcp/spy_magnets.json";
import spyS from "@/tests/fixtures/mcp/spy_stock.json";
import spyTi from "@/tests/fixtures/mcp/spy_trade_insights.json";
import spyCockpitVrp from "@/tests/fixtures/mcp/spy_cockpit_vrp.json";
import spyCockpitDealer from "@/tests/fixtures/mcp/spy_cockpit_dealer.json";
import spyCockpitState from "@/tests/fixtures/mcp/spy_cockpit_state.json";

const EOD = {
  AAPL: aaplT as unknown as TechnicalsResponse,
  SPY: spyT as unknown as TechnicalsResponse,
};
const LIVE = {
  AAPL: aaplLive as unknown as TechnicalsLiveResponse,
  SPY: spyLive as unknown as TechnicalsLiveResponse,
};
const MAGNET = {
  AAPL: aaplM as unknown as MagnetsResponse,
  SPY: spyM as unknown as MagnetsResponse,
};
const STOCK = {
  AAPL: aaplS as unknown as SingleStockReport,
  SPY: spyS as unknown as SingleStockReport,
};
const TI = {
  AAPL: aaplTi as unknown as TradeInsightsResponse,
  SPY: spyTi as unknown as TradeInsightsResponse,
};
const VRP = spyCockpitVrp as unknown as CockpitVrpResponse;
const DEALER = spyCockpitDealer as unknown as CockpitDealerResponse;
const STATE = spyCockpitState as unknown as CockpitStateResponse;

type Snap = {
  ticker: string;
  technicals: Record<string, unknown>;
  chain_flow: Record<string, unknown>;
  term_move: Record<string, unknown>;
  flow_timeline: Record<string, unknown>;
  gamma_bar: Record<string, unknown>;
  charm: Record<string, unknown>;
  vanna: Record<string, unknown>;
  cockpit: Record<string, unknown> | null;
};

function makeCtx(fail: string[] = []) {
  const calls: Record<string, number> = {};
  const apiGet: ToolCtx["apiGet"] = async (path) => {
    calls[path] = (calls[path] ?? 0) + 1;
    const failPath = fail.find((f) => path === f || path.endsWith(f));
    if (failPath) throw new Error(`boom ${failPath}`);
    let m = /^\/stock\/([^/]+)\/technicals$/.exec(path);
    if (m) return EOD[m[1] as keyof typeof EOD];
    m = /^\/stock\/([^/]+)\/technicals\/live$/.exec(path);
    if (m) return LIVE[m[1] as keyof typeof LIVE];
    m = /^\/stock\/([^/]+)\/magnets$/.exec(path);
    if (m) return MAGNET[m[1] as keyof typeof MAGNET];
    m = /^\/stock\/([^/]+)\/trade-insights\/preview$/.exec(path);
    if (m) return TI[m[1] as keyof typeof TI];
    m = /^\/stock\/([^/]+)$/.exec(path);
    if (m) return STOCK[m[1] as keyof typeof STOCK];
    if (path === "/cockpit/SPY/vrp") return VRP;
    if (path === "/cockpit/SPY/dealer") return DEALER;
    if (path === "/cockpit/SPY/state") return STATE;
    throw new Error(`unmapped apiGet path ${path}`);
  };
  const db = {
    query: async () => ({ rows: [{ k: "k1" }] }),
  };
  const ctx: ToolCtx = {
    db: db as unknown as ToolCtx["db"],
    apiGet,
    tokenLabel: "test",
  };
  return { ctx, calls };
}

// scanTicker's module-level EOD cache would leak between tests — reload.
async function loadTool() {
  vi.resetModules();
  return (await import("@/mcp/tools/ticker_snapshot")).tool;
}

describe("ticker_snapshot", () => {
  it("returns every section; each carries as_of or error", async () => {
    const tool = await loadTool();
    const { ctx, calls } = makeCtx();
    const out = (await tool.handler({ ticker: "aapl" }, ctx)) as Snap;
    expect(out.ticker).toBe("AAPL"); // upper-cased
    for (const key of [
      "technicals",
      "chain_flow",
      "term_move",
      "flow_timeline",
      "gamma_bar",
      "charm",
      "vanna",
    ]) {
      const sec = out[key as keyof Snap] as Record<string, unknown>;
      expect(sec).toBeTruthy();
      expect("error" in sec).toBe(false);
      expect(sec).toHaveProperty("as_of");
    }
    expect(out.cockpit).toBeNull(); // AAPL is not a cockpit ticker
    // Fetch sharing: one GET each for the shared payloads.
    expect(calls["/stock/AAPL"]).toBe(1);
    expect(calls["/stock/AAPL/trade-insights/preview"]).toBe(1);
    // The persisting route is never called.
    expect(calls["/stock/AAPL/trade-insights"]).toBeUndefined();
    // No cockpit GETs for a non-cockpit ticker.
    expect(Object.keys(calls).some((p) => p.startsWith("/cockpit/"))).toBe(
      false,
    );
    // Section as-of fields come from the payloads' own date fields.
    expect(out.chain_flow.as_of).toBe(TI.AAPL.as_of);
    expect(out.term_move.as_of).toBe(TI.AAPL.as_of);
    expect(out.flow_timeline.as_of).toBe(STOCK.AAPL.generated_at);
    expect(out.gamma_bar.as_of).toBe(STOCK.AAPL.generated_at);
  });

  it("SPY gets the cockpit section with state pass-through values", async () => {
    const tool = await loadTool();
    const { ctx, calls } = makeCtx();
    const out = (await tool.handler({ ticker: "SPY" }, ctx)) as Snap;
    const cockpit = out.cockpit!;
    expect(cockpit).toBeTruthy();
    expect(cockpit.as_of).toBe(STATE.state.market_date);
    // Pass-through: actual payload values, not recomputed.
    const state = cockpit.state as typeof STATE.state;
    expect(state.vrp_zscore_60d).toBe(STATE.state.vrp_zscore_60d);
    expect(state.vrp_zscore_252d).toBe(STATE.state.vrp_zscore_252d);
    expect(state.vrp_state).toBe(STATE.state.vrp_state);
    // VRP derivation parity with the lib the tab now calls.
    const stats = vrpStats(VRP.points!);
    const vrp = cockpit.vrp as { stats: { mean: number; std: number } };
    expect(vrp.stats).toEqual(stats);
    // Dealer derivation parity on the first-six expiry groups.
    const groups = groupByExpiry(DEALER.points!).slice(0, 6);
    const dealer = cockpit.dealer as {
      totals: { vanna: number; charm: number };
      peaks: { vannaStrike: number | null; charmStrike: number | null };
      primary_expiry: string;
    };
    expect(dealer.primary_expiry).toBe("2026-09-23");
    expect(dealer.totals).toEqual(totals(groups[0][1]));
    expect(dealer.peaks).toEqual(peaks(groups[0][1]));
    for (const p of ["/cockpit/SPY/vrp", "/cockpit/SPY/dealer", "/cockpit/SPY/state"])
      expect(calls[p]).toBe(1);
  });

  it("a failed cockpit endpoint isolates to cockpit: { error } only", async () => {
    const tool = await loadTool();
    const { ctx } = makeCtx(["/cockpit/SPY/dealer"]);
    const out = (await tool.handler({ ticker: "SPY" }, ctx)) as Snap;
    expect(out.cockpit).toHaveProperty("error");
    expect(String((out.cockpit as { error: string }).error)).toContain(
      "dealer",
    );
    for (const key of [
      "technicals",
      "chain_flow",
      "term_move",
      "flow_timeline",
      "gamma_bar",
      "charm",
      "vanna",
    ]) {
      expect(out[key as keyof Snap]).not.toHaveProperty("error");
    }
  });

  it("a failed /stock GET isolates to the four stock-derived sections", async () => {
    const tool = await loadTool();
    const { ctx } = makeCtx(["/stock/AAPL"]); // matches /stock/AAPL exactly via endsWith? no — exact
    const out = (await tool.handler({ ticker: "AAPL" }, ctx)) as Snap;
    // /stock/AAPL is the shared payload: its four dependents all error out…
    for (const key of ["flow_timeline", "gamma_bar", "charm", "vanna"])
      expect(out[key as keyof Snap]).toHaveProperty("error");
    // …while the independently-fetched sections still succeed.
    for (const key of ["technicals", "chain_flow", "term_move"])
      expect(out[key as keyof Snap]).not.toHaveProperty("error");
  });

  it("section values equal the lib functions on the same payloads", async () => {
    const tool = await loadTool();
    const { ctx } = makeCtx();
    const out = (await tool.handler({ ticker: "AAPL" }, ctx)) as Snap;
    expect(out.chain_flow.tapeRatio).toBe(
      chainFlowRead(TI.AAPL.flow_table).tapeRatio,
    );
    expect(out.chain_flow.flowRead).toBe(
      chainFlowRead(TI.AAPL.flow_table).flowRead,
    );
    expect(out.term_move.curveRead).toBe(
      termMoveRead(TI.AAPL.term_structure_table).curveRead,
    );
    const tl = flowTimelineSeries(STOCK.AAPL.options_timeline!);
    expect(out.flow_timeline.totalVol).toEqual(tl.totalVol);
    expect(out.flow_timeline.pcVol).toEqual(tl.pcVol);
    const gb = gammaBarTiles(STOCK.AAPL);
    expect(out.gamma_bar.topWallStrike).toBe(gb.topWallStrike);
    expect(out.gamma_bar.deltaPct).toBe(gb.deltaPct);
    const summary = [...STOCK.AAPL.exposures_summary!].sort((a, b) =>
      a.expiry < b.expiry ? -1 : 1,
    );
    const exp = summary.find((r) => r.expiry === "2026-09-18")!;
    const rowsFor = (STOCK.AAPL.strike_exposures ?? []).filter(
      (r) => r.expiry === exp.expiry,
    );
    expect(out.charm.curve).toEqual(netExposureCurve(rowsFor, "charm"));
    expect(out.vanna.curve).toEqual(netExposureCurve(rowsFor, "vanna"));
    expect(out.charm.expiry).toBe("2026-09-18");
    // Technicals section is the scanTicker '*' row + as_of.
    expect(out.technicals.ticker).toBe("AAPL");
    // The frozen live head predates the EOD as_of, so it is not merged and
    // as_of.live is null — same rule as the UI's freshness check.
    expect(out.technicals.as_of).toEqual({
      eod: EOD.AAPL.as_of,
      live: null,
    });
    expect(out.technicals).toHaveProperty("ema20");
    expect(out.technicals).toHaveProperty("chanlun_points_n");
  });

  it("rejects a traversal probe in ticker before any apiGet", async () => {
    const tool = await loadTool();
    const { ctx, calls } = makeCtx();
    for (const probe of ["../%68%65%61%6c%74%68#", "../health", "a/b", ".."]) {
      await expect(tool.handler({ ticker: probe }, ctx)).rejects.toThrow(
        /invalid ticker/,
      );
    }
    expect(calls).toEqual({}); // the probe never reached a URL
    // The input schema rejects it too (what the SDK enforces on the wire).
    const schema = z.object(tool.inputSchema);
    expect(
      schema.safeParse({ ticker: "../%68%65%61%6c%74%68#" }).success,
    ).toBe(false);
    expect(schema.safeParse({ ticker: "brk.b" }).success).toBe(true);
  });
});
