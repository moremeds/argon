// regime_state — stub ToolCtx serves the frozen regime fixtures; the
// assertions pin section shape, single /regime/quotes fetch sharing, the
// vcg/vrp live→EOD fallbacks, per-section error isolation, and value parity
// with the web/lib/regime/derive functions the UI now calls.
import { afterEach, describe, expect, it, vi } from "vitest";
import type { ToolCtx } from "@/mcp/types";
import { tool } from "@/mcp/tools/regime_state";
import {
  liveSpotSelection,
  retagProfileForSpot,
} from "@/lib/regime/derive/gex";
import {
  symbolRead,
  termStructureRead,
} from "@/lib/regime/derive/volBackdrop";
import {
  priorComponentScore,
  priorHistoryRow,
} from "@/lib/regime/derive/cri";
import type { GexData } from "@/lib/regime/useGex";
import type { VolBackdropData } from "@/lib/regime/useVolBackdrop";
import type { RegimeQuotesResponse } from "@/lib/regime/useRegimeQuotes";
import type { CriLiveResponse } from "@/lib/regime/useCriLive";
import type { CriDailyEntry } from "@/lib/regime/useCriSeries";
import type { components } from "@/lib/types";
import gexFixture from "../fixtures/mcp/regime_gex.json";
import quotesFixture from "../fixtures/mcp/regime_quotes.json";
import vbFixture from "../fixtures/mcp/regime_vol_backdrop.json";
import criLiveFixture from "../fixtures/mcp/regime_cri_live.json";
import criHistFixture from "../fixtures/mcp/regime_cri_history.json";
import vcgFixture from "../fixtures/mcp/regime_vcg.json";
import vcgLiveFixture from "../fixtures/mcp/regime_vcg_live.json";
import vrpFixture from "../fixtures/mcp/regime_vrp_macro_signal.json";
import vrpLiveFixture from "../fixtures/mcp/regime_vrp_macro_signal_live.json";

const GEX = gexFixture as unknown as GexData;
const QUOTES = quotesFixture as unknown as RegimeQuotesResponse;
const VB = vbFixture as unknown as VolBackdropData;
const CRIL = criLiveFixture as unknown as CriLiveResponse;
const CRIH_ROWS = criHistFixture.rows as unknown as CriDailyEntry[];
const VCGE = vcgFixture as unknown as components["schemas"]["VcgResponse"];
const VCGL = vcgLiveFixture as unknown as components["schemas"]["VcgLiveResponse"];
const VRPE = vrpFixture as unknown as components["schemas"]["VrpMacroSignalResponse"];
const VRPL = vrpLiveFixture as unknown as components["schemas"]["VrpMacroSignalLiveResponse"];

type Out = {
  gex: Record<string, unknown>;
  vol_backdrop: Record<string, unknown>;
  cri: Record<string, unknown>;
  vcg: Record<string, unknown>;
  vrp_macro: Record<string, unknown>;
};

function makeCtx(opts: {
  fail?: string[];
  dropLive?: string[]; // vcg | vrp-macro-signal live endpoints throw → EOD
} = {}) {
  const calls: Record<string, number> = {};
  const apiGet: ToolCtx["apiGet"] = async (path) => {
    calls[path] = (calls[path] ?? 0) + 1;
    if (opts.fail?.some((f) => path === f)) throw new Error(`boom ${path}`);
    if (opts.dropLive?.includes("vcg") && path === "/regime/vcg/live")
      throw new Error("live unavailable");
    if (
      opts.dropLive?.includes("vrp") &&
      path === "/regime/vrp-macro-signal/live"
    )
      throw new Error("live unavailable");
    switch (path) {
      case "/regime/quotes":
        return QUOTES;
      case "/regime/gex":
        return GEX;
      case "/regime/vol-backdrop":
        return VB;
      case "/regime/cri/live":
        return CRIL;
      case "/regime/cri/history":
        return { rows: CRIH_ROWS };
      case "/regime/vcg/live":
        return VCGL;
      case "/regime/vcg":
        return VCGE;
      case "/regime/vrp-macro-signal/live":
        return VRPL;
      case "/regime/vrp-macro-signal":
        return VRPE;
    }
    throw new Error(`unmapped apiGet path ${path}`);
  };
  const ctx: ToolCtx = {
    db: { query: async () => ({ rows: [] }) } as unknown as ToolCtx["db"],
    apiGet,
    tokenLabel: "test",
  };
  return { ctx, calls };
}

// Clock anchors: the quotes fixture's quoted_at values are months older than
// real now → the default assertions exercise the stale/EOD paths verbatim.
// For the live path, system time is pinned 60 s after the VIX quote.
const NOW_FRESH = Date.parse(QUOTES.quotes!.VIX.quoted_at) + 60_000;

afterEach(() => {
  vi.useRealTimers();
});

describe("shape + shared quote fetch", () => {
  it("returns all five sections, each with as_of", async () => {
    const { ctx, calls } = makeCtx();
    const out = (await tool.handler({}, ctx)) as Out;
    for (const k of ["gex", "vol_backdrop", "cri", "vcg", "vrp_macro"]) {
      expect(out[k as keyof Out]).toBeDefined();
      expect(out[k as keyof Out].error).toBeUndefined();
      expect(out[k as keyof Out].as_of).toBeDefined();
    }
    // One shared quotes fetch despite two quote-consuming sections.
    expect(calls["/regime/quotes"]).toBe(1);
    expect(calls["/regime/gex"]).toBe(1);
    expect(calls["/regime/vcg/live"]).toBe(1);
    expect(calls["/regime/vcg"]).toBeUndefined();
  });
});

describe("gex section", () => {
  it("stale SPX quote → EOD values, payload profile untouched", async () => {
    const { ctx } = makeCtx();
    const out = (await tool.handler({}, ctx)) as Out;
    expect(out.gex.as_of).toBe("2026-09-23T14:24:02.024708+00:00");
    expect(out.gex.spot).toBe(7716.87);
    expect(out.gex.live_spot).toBeNull();
    expect(out.gex.display_spot).toBe(7716.87);
    expect(out.gex.flip).toEqual(GEX.levels.gex_flip);
    expect(out.gex.levels).toEqual(GEX.levels);
    expect(out.gex.profile).toEqual(GEX.profile);
  });

  it("fresh SPX quote → live spot used and profile retagged", async () => {
    vi.setSystemTime(NOW_FRESH);
    const { ctx } = makeCtx();
    const out = (await tool.handler({}, ctx)) as Out;
    const sel = liveSpotSelection(GEX.ticker, GEX.tape_time, QUOTES, NOW_FRESH);
    expect(out.gex.live_spot).toBe(sel.liveSpot);
    expect(out.gex.live_spot).toBe(7575.39);
    expect(out.gex.display_spot).toBe(7575.39);
    const expected = retagProfileForSpot(GEX.profile, 7575.39, GEX.levels);
    expect(out.gex.profile).toEqual(expected);
    expect(
      (expected as GexData["profile"]).filter((b) => b.tag === "SPOT")
        .map((b) => b.strike),
    ).toEqual([7575]);
  });
});

describe("vol_backdrop section", () => {
  it("stale quotes → EOD ratio/state + close-over-close symbols", async () => {
    const { ctx } = makeCtx();
    const out = (await tool.handler({}, ctx)) as Out;
    const now = Date.now();
    const ts = termStructureRead(VB, QUOTES, now);
    expect(out.vol_backdrop.as_of).toBe("2026-09-18");
    expect(out.vol_backdrop.ratio).toBe(0.811951754385965);
    expect(out.vol_backdrop.ratio).toBe(ts.ratio);
    expect(out.vol_backdrop.state).toBe("contango");
    expect(out.vol_backdrop.ratio_source).toBe("eod");
    const syms = out.vol_backdrop.symbols as Record<
      string,
      { live: boolean; last: number | null; change_pct: number | null }
    >;
    for (const s of ["VIX", "VIX3M", "VVIX", "COR1M"] as const) {
      const r = symbolRead(s, VB, QUOTES, now);
      expect(syms[s]).toEqual({ live: r.live, last: r.close, change_pct: r.chg });
    }
    expect(syms.VIX.last).toBe(14.81);
    expect(syms.VIX.change_pct).toBeCloseTo(-4.08031088082901, 12);
  });

  it("fresh VIX/VIX3M quotes → live ratio", async () => {
    vi.setSystemTime(NOW_FRESH);
    const { ctx } = makeCtx();
    const out = (await tool.handler({}, ctx)) as Out;
    const ts = termStructureRead(VB, QUOTES, NOW_FRESH);
    expect(out.vol_backdrop.ratio_source).toBe("live");
    expect(out.vol_backdrop.ratio).toBe(ts.ratio);
    expect(out.vol_backdrop.ratio).toBeCloseTo(0.8093699515347333, 12);
  });
});

describe("cri section", () => {
  it("pass-through + prior scores + history derivations", async () => {
    const { ctx } = makeCtx();
    const out = (await tool.handler({}, ctx)) as Out;
    expect(out.cri.as_of).toBe("2026-09-19T15:19:59.998761+08:00");
    expect(out.cri.basis).toBe("eod");
    expect(out.cri.score).toBe(8.0);
    expect(out.cri.level).toBe("LOW");
    expect(out.cri.components).toEqual({
      vix: 1.0,
      vvix: 3.9,
      correlation: 0.0,
      momentum: 3.1,
    });
    const prior = priorHistoryRow(CRIL);
    expect(out.cri.prior_components).toEqual({
      vix: priorComponentScore(prior, "vix"),
      vvix: priorComponentScore(prior, "vvix"),
      correlation: priorComponentScore(prior, "correlation"),
      momentum: priorComponentScore(prior, "momentum"),
    });
    expect(out.cri.prior_components).toEqual({
      vix: 1.4,
      vvix: 3.4,
      correlation: 0,
      momentum: 3.6,
    });
    expect(out.cri.vix_delta_3d as number).toBeCloseTo(-2.39, 10);
    expect(out.cri.spx_last).toBe(7650.5);
    expect(out.cri.history_as_of).toBe("2026-09-18");
  });
});

describe("vcg + vrp_macro sections", () => {
  it("live payloads pass through with basis", async () => {
    const { ctx } = makeCtx();
    const out = (await tool.handler({}, ctx)) as Out;
    expect(out.vcg.as_of).toBe("2026-09-19T15:24:59.923896+08:00");
    expect(out.vcg.basis).toBe("eod");
    expect(out.vcg.signal).toEqual(VCGL.signal);
    expect(out.vcg.history).toBeUndefined(); // bulky array dropped
    expect(out.vrp_macro.basis).toBe("eod");
    expect(out.vrp_macro.signal).toEqual(VRPL.signal);
    expect(out.vrp_macro.as_of).toBe("2026-09-23"); // signal.snapshot_date
  });

  it("vcg live failure falls back to the EOD payload", async () => {
    const { ctx, calls } = makeCtx({ dropLive: ["vcg"] });
    const out = (await tool.handler({}, ctx)) as Out;
    expect(calls["/regime/vcg/live"]).toBe(1);
    expect(calls["/regime/vcg"]).toBe(1);
    expect(out.vcg.error).toBeUndefined();
    expect(out.vcg.as_of).toBe("2026-09-19T15:24:59.923896+08:00");
    expect(out.vcg.basis).toBeNull(); // EOD payload has no basis field
    expect(out.vcg.signal).toEqual(VCGE.signal);
  });

  it("vrp_macro live failure falls back to the EOD signals array", async () => {
    const { ctx, calls } = makeCtx({ dropLive: ["vrp"] });
    const out = (await tool.handler({}, ctx)) as Out;
    expect(calls["/regime/vrp-macro-signal/live"]).toBe(1);
    expect(calls["/regime/vrp-macro-signal"]).toBe(1);
    expect(out.vrp_macro.error).toBeUndefined();
    expect(out.vrp_macro.signals).toEqual(VRPE.signals);
    expect(out.vrp_macro.as_of).toBe("2026-09-23");
    expect(out.vrp_macro.basis).toBeNull();
  });
});

describe("error isolation", () => {
  it("a failed endpoint only errors its own section", async () => {
    const { ctx } = makeCtx({ fail: ["/regime/gex"] });
    const out = (await tool.handler({}, ctx)) as Out;
    expect(String(out.gex.error)).toContain("/regime/gex");
    for (const k of ["vol_backdrop", "cri", "vcg", "vrp_macro"] as const) {
      expect(out[k].error).toBeUndefined();
    }
  });

  it("a failed quotes call degrades dependents to EOD, not {error}", async () => {
    const { ctx } = makeCtx({ fail: ["/regime/quotes"] });
    const out = (await tool.handler({}, ctx)) as Out;
    expect(out.gex.error).toBeUndefined();
    expect(out.gex.live_spot).toBeNull();
    expect(out.vol_backdrop.error).toBeUndefined();
    expect(out.vol_backdrop.ratio_source).toBe("eod");
  });

  it("cri history failure errors only the cri section", async () => {
    const { ctx } = makeCtx({ fail: ["/regime/cri/history"] });
    const out = (await tool.handler({}, ctx)) as Out;
    expect(String(out.cri.error)).toContain("cri/history");
    expect(out.gex.error).toBeUndefined();
  });
});
