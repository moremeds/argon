// technicals_scan against a stubbed ToolCtx serving the frozen real fixtures
// (tests/fixtures/mcp, see its README). The oracle is the same call chain the
// UI makes: mergeLiveHead → technicalsOverlays → the T1b verdict/distribution
// helpers — run directly on the same payloads.
import { describe, expect, it, vi } from "vitest";
import type { Columnar, ToolCtx } from "@/mcp/types";
import type {
  MagnetsResponse,
  TechnicalsLiveResponse,
  TechnicalsResponse,
} from "@/lib/api";
import { mergeLiveHead } from "@/lib/technicals/series";
import { technicalsOverlays } from "@/lib/technicals/overlays";
import { macdSignalText } from "@/lib/technicals/verdicts";
import { returnDistribution } from "@/lib/technicals/returnDistribution";
import { kinematicsLeg, volumeTile } from "@/lib/magnetTiles";
import aapl from "@/tests/fixtures/mcp/aapl_technicals.json";
import nvda from "@/tests/fixtures/mcp/nvda_technicals.json";
import spy from "@/tests/fixtures/mcp/spy_technicals.json";
import aaplLive from "@/tests/fixtures/mcp/aapl_technicals_live.json";
import nvdaLive from "@/tests/fixtures/mcp/nvda_technicals_live.json";
import spyLive from "@/tests/fixtures/mcp/spy_technicals_live.json";
import aaplM from "@/tests/fixtures/mcp/aapl_magnets.json";
import nvdaM from "@/tests/fixtures/mcp/nvda_magnets.json";
import spyM from "@/tests/fixtures/mcp/spy_magnets.json";
import watchlist from "@/tests/fixtures/mcp/watchlist.json";

const EOD: Record<string, TechnicalsResponse> = {
  AAPL: aapl as unknown as TechnicalsResponse,
  NVDA: nvda as unknown as TechnicalsResponse,
  SPY: spy as unknown as TechnicalsResponse,
};
const LIVE: Record<string, TechnicalsLiveResponse> = {
  AAPL: aaplLive as unknown as TechnicalsLiveResponse,
  NVDA: nvdaLive as unknown as TechnicalsLiveResponse,
  SPY: spyLive as unknown as TechnicalsLiveResponse,
};
const MAGNET: Record<string, MagnetsResponse> = {
  AAPL: aaplM as unknown as MagnetsResponse,
  NVDA: nvdaM as unknown as MagnetsResponse,
  SPY: spyM as unknown as MagnetsResponse,
};
const TICKERS = ["AAPL", "NVDA", "SPY"];

// The stub's /watchlist is the real fixture's shape filtered to the tickers we
// have payloads for — the stub stands in for the endpoint, so its roster is
// the stub's own choice.
const WATCHLIST = {
  ...(watchlist as object),
  tickers: (watchlist as { tickers: { ticker: string }[] }).tickers.filter(
    (t) => TICKERS.includes(t.ticker),
  ),
};

type StubOpts = {
  eod?: Record<string, unknown>;
  tickers?: string[];
  failEod?: string[];
  failLive?: string[];
  key?: () => string;
};

function makeCtx(opts: StubOpts = {}) {
  const eod = opts.eod ?? EOD;
  const roster = opts.tickers ?? WATCHLIST.tickers.map((t) => t.ticker);
  const stats = {
    inflight: 0,
    maxInflight: 0,
    eodGets: [] as string[],
    liveGets: [] as string[],
    magnetGets: [] as string[],
    keyCalls: 0,
  };
  const apiGet: ToolCtx["apiGet"] = async (path) => {
    stats.inflight++;
    stats.maxInflight = Math.max(stats.maxInflight, stats.inflight);
    try {
      // One macrotask of latency so pooled requests overlap measurably.
      await new Promise((r) => setTimeout(r, 0));
      if (path === "/watchlist")
        return {
          ...WATCHLIST,
          tickers: roster.map((t) => ({ ticker: t })),
        };
      let m = /^\/stock\/([^/]+)\/technicals$/.exec(path);
      if (m) {
        stats.eodGets.push(m[1]);
        if (opts.failEod?.includes(m[1]))
          throw new Error(`eod boom ${m[1]}`);
        return eod[m[1]];
      }
      m = /^\/stock\/([^/]+)\/technicals\/live$/.exec(path);
      if (m) {
        stats.liveGets.push(m[1]);
        if (opts.failLive?.includes(m[1]))
          throw new Error(`live boom ${m[1]}`);
        return LIVE[m[1]];
      }
      m = /^\/stock\/([^/]+)\/magnets$/.exec(path);
      if (m) {
        stats.magnetGets.push(m[1]);
        return MAGNET[m[1]];
      }
      throw new Error(`unmapped apiGet path ${path}`);
    } finally {
      stats.inflight--;
    }
  };
  const db = {
    query: async (sql: string) => {
      stats.keyCalls++;
      expect(sql).toContain("uw_scan.technical_daily");
      return { rows: [{ k: opts.key?.() ?? "k1" }] };
    },
  };
  const ctx: ToolCtx = {
    db: db as unknown as ToolCtx["db"],
    apiGet,
    tokenLabel: "test",
  };
  return { ctx, stats };
}

// The module keeps the EOD cache + invalidation-key throttle as module state —
// reset and re-import per test for a clean cache.
async function loadTool() {
  vi.resetModules();
  return (await import("@/mcp/tools/technicals_scan")).tool;
}

const cell = (out: Columnar, row: unknown[], field: string) =>
  row[out.columns.indexOf(field)];

describe("technicals_scan", () => {
  it("(a) returns the columnar shape with default columns over the watchlist", async () => {
    const tool = await loadTool();
    const { ctx, stats } = makeCtx();
    const out = (await tool.handler({}, ctx)) as Columnar;
    expect(out.columns[0]).toBe("ticker");
    expect(out.columns[1]).toBe("error");
    for (const f of [
      "price",
      "ema20",
      "vp_poc",
      "chanlun_points_n",
      "ret_skew",
      "fvg_n",
      "macd_signal",
      "kinematics",
      "alignment",
      "hve_last",
      "vol_ma50",
    ])
      expect(out.columns).toContain(f);
    // `*`/extra fields are not in the compact default.
    for (const f of ["detail", "chanlun", "vp", "magnet_velocity"])
      expect(out.columns).not.toContain(f);
    expect(out.rows).toHaveLength(3);
    expect(out.rows.map((r) => r[0]).sort()).toEqual([...TICKERS].sort());
    for (const row of out.rows) {
      expect(row).toHaveLength(out.columns.length);
      expect(row[1]).toBeNull();
    }
    // EOD as_of is the frozen payloads' date; every fixture live payload is
    // months stale vs now, so nothing merged.
    expect(out.as_of.eod).toBe("2026-09-18");
    expect(out.as_of.live).toBeNull();
    // No magnet fields requested → no magnets GETs (2 GETs per ticker).
    expect(stats.magnetGets).toHaveLength(0);
    expect(stats.eodGets).toHaveLength(3);
    expect(stats.liveGets).toHaveLength(3);
    expect(stats.keyCalls).toBe(1);
  });

  it("(b) honors tickers, fields and rejects unknown fields", async () => {
    const tool = await loadTool();
    const { ctx } = makeCtx();
    const out = (await tool.handler(
      { tickers: ["aapl", "nvda"], fields: ["rsi14", "price"] },
      ctx,
    )) as Columnar;
    expect(out.columns).toEqual(["ticker", "error", "rsi14", "price"]);
    expect(out.rows.map((r) => r[0])).toEqual(["AAPL", "NVDA"]);
    expect(out.rows[0]).toHaveLength(4);

    await expect(
      tool.handler({ fields: ["price", "bogus"] }, ctx),
    ).rejects.toThrow(/unknown field\(s\) bogus/);
    await expect(
      tool.handler({ fields: ["bogus"] }, ctx),
    ).rejects.toThrow(/rsi14/); // the error lists the valid names

    const all = (await tool.handler(
      { tickers: ["SPY"], fields: ["*"] },
      ctx,
    )) as Columnar;
    for (const f of [
      "detail",
      "chanlun",
      "vp",
      "fvg_gaps",
      "return_distribution",
      "forward_returns",
      "vwap_anchor",
      "macd_watchlist_pctile",
      "magnet_velocity",
      "magnet_vol_ratio",
    ])
      expect(all.columns).toContain(f);
  });

  it("(c) values equal the direct mergeLiveHead → overlays call", async () => {
    const tool = await loadTool();
    const { ctx } = makeCtx();
    const out = (await tool.handler(
      { tickers: ["AAPL"], fields: ["*"] },
      ctx,
    )) as Columnar;
    const row = out.rows[0];
    const data = mergeLiveHead(EOD.AAPL, LIVE.AAPL, Date.now());
    const ov = technicalsOverlays(data, "1y");
    const det = (data.detail ?? {}) as {
      dual_macd?: Parameters<typeof macdSignalText>[0];
    };
    expect(cell(out, row, "ema20")).toBeCloseTo(ov.ema20.at(-1) ?? NaN, 12);
    expect(cell(out, row, "bb_upper")).toBeCloseTo(
      ov.bollinger.upper.at(-1) ?? NaN,
      12,
    );
    expect(cell(out, row, "vol_ma50")).toBeCloseTo(
      ov.volMa50.at(-1) ?? NaN,
      12,
    );
    expect(cell(out, row, "vp_poc")).toBe(ov.vp.stats?.poc);
    expect(cell(out, row, "vp_bias")).toBe(ov.vp.stats?.bias);
    expect(cell(out, row, "chanlun_points_n")).toBe(
      ov.chanlun.result.points.length,
    );
    expect(cell(out, row, "chanlun")).toEqual(ov.chanlun.result);
    expect(cell(out, row, "fvg_n")).toBe(ov.fvg.gaps.length);
    expect(cell(out, row, "fvg_gaps")).toEqual(ov.fvg.gaps);
    expect(cell(out, row, "macd_signal")).toBe(
      macdSignalText(det.dual_macd)?.text ?? null,
    );
    expect(cell(out, row, "ret_skew")).toBe(
      returnDistribution(data.series).skew,
    );
    expect(cell(out, row, "price")).toBe(data.header?.price);
    expect(cell(out, row, "eod_as_of")).toBe("2026-09-18");
    expect(cell(out, row, "live_captured_at")).toBeNull();
    // Magnet fields come from the T1b helpers on the magnets candles.
    const mt = volumeTile(MAGNET.AAPL.candles);
    const kl = kinematicsLeg(MAGNET.AAPL.candles.map((c) => c.close));
    expect(cell(out, row, "magnet_vol_last")).toBe(mt.lastVol);
    expect(cell(out, row, "magnet_vol_ratio")).toBe(mt.ratio);
    expect(cell(out, row, "magnet_velocity")).toBe(kl.v);
    expect(cell(out, row, "magnet_accel")).toBe(kl.accel);

    // timeframe only moves the FVG window.
    const q3 = (await tool.handler(
      { tickers: ["AAPL"], fields: ["fvg_n"], timeframe: "3m" },
      ctx,
    )) as Columnar;
    expect(q3.rows[0][q3.columns.indexOf("fvg_n")]).toBe(
      technicalsOverlays(data, "3m").fvg.gaps.length,
    );
  });

  it("(d) reuses the EOD cache and re-fetches only live on the second call", async () => {
    const tool = await loadTool();
    const { ctx, stats } = makeCtx();
    await tool.handler({}, ctx);
    await tool.handler({}, ctx);
    expect(stats.eodGets).toHaveLength(3); // no EOD refetch
    expect(stats.liveGets).toHaveLength(6); // live is never cached
    expect(stats.keyCalls).toBe(1); // key re-check is throttled to 60 s
  });

  it("(e) refetches EOD when the invalidation key changes after the 60 s gate", async () => {
    const tool = await loadTool();
    let cur = "k1";
    const { ctx, stats } = makeCtx({ key: () => cur });
    await tool.handler({}, ctx);
    cur = "k2";
    // Advance the re-check clock past the 60 s throttle without fake timers.
    const realNow = Date.now();
    const spyNow = vi
      .spyOn(Date, "now")
      .mockReturnValue(realNow + 61_000);
    try {
      await tool.handler({}, ctx);
    } finally {
      spyNow.mockRestore();
    }
    expect(stats.keyCalls).toBe(2);
    expect(stats.eodGets).toHaveLength(6); // cache dropped → all refetched
    expect(stats.liveGets).toHaveLength(6);
  });

  it("(f) a failed ticker yields an error row while the others succeed", async () => {
    const tool = await loadTool();
    const { ctx } = makeCtx({ failEod: ["NVDA"] });
    const out = (await tool.handler({}, ctx)) as Columnar;
    const byTicker = new Map(out.rows.map((r) => [r[0], r]));
    const bad = byTicker.get("NVDA")!;
    expect(bad[1]).toMatch(/eod boom NVDA/);
    expect(bad.slice(2).every((c) => c === null)).toBe(true);
    const good = byTicker.get("AAPL")!;
    expect(good[1]).toBeNull();
    expect(cell(out, good, "price")).not.toBeNull();
    // as_of is taken over the successful rows only.
    expect(out.as_of.eod).toBe("2026-09-18");
  });

  it("(g) never exceeds the 8-in-flight cap", async () => {
    const tool = await loadTool();
    // One scan's per-ticker GETs are sequential (EOD → live → magnets), so 3
    // tickers alone peak at 3 in flight. Run three scans concurrently instead:
    // the module-level pool is shared, so 9 cold-cache pipelines × the
    // magnet_* third GET queue >8 requests — the cap binds with only real
    // fixture tickers.
    const { ctx, stats } = makeCtx();
    const outs = (await Promise.all(
      [0, 1, 2].map(() =>
        tool.handler(
          { tickers: TICKERS, fields: ["price", "magnet_velocity"] },
          ctx,
        ),
      ),
    )) as Columnar[];
    for (const out of outs) {
      expect(out.rows).toHaveLength(3);
      for (const row of out.rows) expect(row[1]).toBeNull();
    }
    expect(stats.maxInflight).toBe(8);
    // 3 concurrent calls × 3 tickers, all cold → 9 EOD GETs; the invalidation
    // key check single-flights into one query.
    expect(stats.eodGets).toHaveLength(9);
    expect(stats.magnetGets).toHaveLength(9);
    expect(stats.keyCalls).toBe(1);
  });

  it("(h) exported scanTicker returns the same row keyed by field name", async () => {
    const mod = await (async () => {
      vi.resetModules();
      return await import("@/mcp/tools/technicals_scan");
    })();
    const { ctx, stats } = makeCtx();
    // Success: object keys are ticker/error/fields and match the columnar row.
    const row = await mod.scanTicker(ctx, "aapl", {
      fields: ["price", "ema20", "vp_poc"],
    });
    expect(Object.keys(row).sort()).toEqual(
      ["ticker", "error", "price", "ema20", "vp_poc"].sort(),
    );
    const out = (await mod.tool.handler(
      { tickers: ["AAPL"], fields: ["price", "ema20", "vp_poc"] },
      ctx,
    )) as Columnar;
    expect(row.ticker).toBe("AAPL");
    expect(row.error).toBeNull();
    for (const f of ["price", "ema20", "vp_poc"])
      expect(row[f]).toEqual(out.rows[0][out.columns.indexOf(f)]);
    // The exported call shares the module EOD cache — the handler call after
    // it did zero extra EOD GETs.
    expect(stats.eodGets).toEqual(["AAPL"]);
    // Error path: { ticker, error, fields...: null }.
    const { ctx: ctx2 } = makeCtx({ failEod: ["NVDA"] });
    const bad = await mod.scanTicker(ctx2, "nvda", { fields: ["price"] });
    expect(bad.ticker).toBe("NVDA");
    expect(bad.error).toMatch(/eod boom NVDA/);
    expect(bad.price).toBeNull();
    // Unknown fields reject identically to the handler.
    await expect(
      mod.scanTicker(ctx, "AAPL", { fields: ["nope"] }),
    ).rejects.toThrow(/unknown field/);
  });
});
