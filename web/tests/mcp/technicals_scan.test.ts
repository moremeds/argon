// technicals_scan against a stubbed ToolCtx serving the frozen real fixtures
// (tests/fixtures/mcp, see its README). The oracle is the same call chain the
// UI makes: mergeLiveHead → technicalsOverlays → the T1b verdict/distribution
// helpers — run directly on the same payloads.
import { describe, expect, it, vi } from "vitest";
import { z } from "zod";
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
  live?: Record<string, unknown>;
  tickers?: string[];
  failEod?: string[];
  failLive?: string[];
  key?: () => string;
};

function makeCtx(opts: StubOpts = {}) {
  const eod = opts.eod ?? EOD;
  const live = opts.live ?? LIVE;
  const roster = opts.tickers ?? WATCHLIST.tickers.map((t) => t.ticker);
  const stats = {
    inflight: 0,
    maxInflight: 0,
    paths: [] as string[],
    eodGets: [] as string[],
    liveGets: [] as string[],
    magnetGets: [] as string[],
    keyCalls: 0,
  };
  const apiGet: ToolCtx["apiGet"] = async (path) => {
    stats.paths.push(path);
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
        return live[m[1]];
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
      // The invalidation key must cover both tables the /technicals payload
      // is built from — dailies AND the user-set VWAP anchors.
      expect(sql).toContain("uw_scan.technical_daily");
      expect(sql).toContain("uw_scan.technical_vwap_anchor");
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

  it("(i) a vwap-anchor-only key change drops the EOD cache", async () => {
    const tool = await loadTool();
    // Key shape is "<max inserted_at>|<count>:<max computed_at>". Move only
    // the anchor half — POST/DELETE vwap-anchor must invalidate too.
    let anchor = "3:2026-10-01";
    const { ctx, stats } = makeCtx({ key: () => `daily1|${anchor}` });
    await tool.handler({}, ctx);
    anchor = "3:2026-10-02";
    const spyNow = vi.spyOn(Date, "now").mockReturnValue(Date.now() + 61_000);
    try {
      await tool.handler({}, ctx);
    } finally {
      spyNow.mockRestore();
    }
    expect(stats.keyCalls).toBe(2);
    expect(stats.eodGets).toHaveLength(6); // cache dropped → all refetched
    // An anchor delete (count moves, max doesn't) invalidates too. The clock
    // must clear the 60 s throttle against the *mocked* eodKeyAt, so the jump
    // is 130 s of real now.
    anchor = "2:2026-10-02";
    const spyNow2 = vi.spyOn(Date, "now").mockReturnValue(Date.now() + 130_000);
    try {
      await tool.handler({}, ctx);
    } finally {
      spyNow2.mockRestore();
    }
    expect(stats.eodGets).toHaveLength(9);
  });

  it("(j) merges a live head captured after the scan started", async () => {
    const tool = await loadTool();
    const t0 = Date.parse("2026-09-18T15:00:00Z"); // 11:00 ET, 2026-09-18
    const captured = new Date(t0 + 60_000).toISOString();
    const { ctx } = makeCtx({
      live: {
        AAPL: {
          ...LIVE.AAPL,
          available: true,
          captured_at: captured,
          spot: 999.99,
        },
      },
    });
    // Scan start reads t0 — BEFORE the capture lands. The merge clock reads
    // t0+120s, after the live payload arrived; a scan-start clock would give
    // the capture a negative age and drop it.
    const spyNow = vi
      .spyOn(Date, "now")
      .mockReturnValueOnce(t0)
      .mockReturnValue(t0 + 120_000);
    try {
      const out = (await tool.handler(
        { tickers: ["AAPL"], fields: ["price", "live_captured_at"] },
        ctx,
      )) as Columnar;
      expect(cell(out, out.rows[0], "live_captured_at")).toBe(captured);
      expect(cell(out, out.rows[0], "price")).toBe(999.99);
    } finally {
      spyNow.mockRestore();
    }
  });

  it("(k) sma fields survive a fresh live row: sma200 from header, rest from last EOD bar", async () => {
    const tool = await loadTool();
    // Fresh capture (real now) → the merge appends a provisional live row
    // that carries none of sma20/sma50/sma200/rs_ratio.
    const { ctx } = makeCtx({
      live: {
        AAPL: {
          ...LIVE.AAPL,
          available: true,
          captured_at: new Date().toISOString(),
        },
      },
    });
    const out = (await tool.handler(
      { tickers: ["AAPL"], fields: ["sma20", "sma50", "sma200", "rs_ratio"] },
      ctx,
    )) as Columnar;
    const row = out.rows[0];
    expect(row[1]).toBeNull();
    const eodLast = EOD.AAPL.series!.at(-1)!;
    expect(cell(out, row, "sma20")).toBe(eodLast.sma20);
    expect(cell(out, row, "sma50")).toBe(eodLast.sma50);
    expect(cell(out, row, "sma200")).toBe(EOD.AAPL.header!.sma200);
    expect(cell(out, row, "rs_ratio")).toBe(eodLast.rs_ratio);
    for (const f of ["sma20", "sma50", "sma200", "rs_ratio"])
      expect(cell(out, row, f)).not.toBeNull();
  });

  it("(l) a traversal probe in tickers rejects the call before any apiGet", async () => {
    const tool = await loadTool();
    const { ctx, stats } = makeCtx();
    for (const probe of ["../%68%65%61%6c%74%68#", "../health", "a/b", ".."]) {
      await expect(
        tool.handler({ tickers: [probe] }, ctx),
      ).rejects.toThrow(/invalid ticker/);
    }
    // Nothing was fetched — the probe never reached a URL.
    expect(stats.paths).toEqual([]);
    expect(stats.keyCalls).toBe(0);
    // The input schema rejects the same probes (what the SDK enforces).
    const schema = z.object(tool.inputSchema);
    expect(
      schema.safeParse({ tickers: ["../%68%65%61%6c%74%68#"] }).success,
    ).toBe(false);
    expect(schema.safeParse({ tickers: ["a/b"] }).success).toBe(false);
    expect(schema.safeParse({ tickers: ["brk.b", "^VIX"] }).success).toBe(true);
  });

  it("(m) a bad watchlist ticker becomes that row's error, not a failed scan", async () => {
    const tool = await loadTool();
    const { ctx, stats } = makeCtx({ tickers: ["AAPL", "../health"] });
    const out = (await tool.handler({}, ctx)) as Columnar;
    const byTicker = new Map(out.rows.map((r) => [r[0], r]));
    expect(byTicker.get("AAPL")![1]).toBeNull();
    const bad = byTicker.get("../health")!;
    expect(bad[1]).toMatch(/invalid ticker/);
    expect(bad.slice(2).every((c) => c === null)).toBe(true);
    // No request path ever carried the poisoned value.
    expect(
      stats.paths.every((p) => !p.includes("..") && !p.includes("health")),
    ).toBe(true);
  });

  it("(n) scanTicker validates its ticker before any fetch", async () => {
    const mod = await (async () => {
      vi.resetModules();
      return await import("@/mcp/tools/technicals_scan");
    })();
    const { ctx, stats } = makeCtx();
    await expect(mod.scanTicker(ctx, "../health")).rejects.toThrow(
      /invalid ticker/,
    );
    await expect(mod.scanTicker(ctx, "%2e%2e/x")).rejects.toThrow(
      /invalid ticker/,
    );
    expect(stats.paths).toEqual([]);
  });

  it("(o) fields=* exposes the full marker lists and VP level lists", async () => {
    const tool = await loadTool();
    const { ctx } = makeCtx();
    const out = (await tool.handler(
      { tickers: TICKERS, fields: ["*"] },
      ctx,
    )) as Columnar;
    for (const f of [
      "hve_markers",
      "low_vol_markers",
      "vp_lvn",
      "vp_zones",
    ])
      expect(out.columns).toContain(f);
    const byTicker = new Map(out.rows.map((r) => [r[0] as string, r]));
    const tt = (m: { time: string; text: string }) => ({
      time: m.time,
      text: m.text,
    });
    for (const t of TICKERS) {
      const row = byTicker.get(t)!;
      expect(row[1]).toBeNull();
      const ov = technicalsOverlays(
        mergeLiveHead(EOD[t], LIVE[t], Date.now()),
        "1y",
      );
      expect(cell(out, row, "hve_markers")).toEqual(
        ov.markers.highVol.map(tt),
      );
      expect(cell(out, row, "low_vol_markers")).toEqual(
        ov.markers.lowVol.map(tt),
      );
      expect(cell(out, row, "vp_lvn")).toEqual(ov.vp.lvn);
      expect(cell(out, row, "vp_zones")).toEqual(ov.vp.zones);
    }
  });

  it("(p) AAPL marker counts pinned to the fixture's literal sizes", async () => {
    const tool = await loadTool();
    const { ctx } = makeCtx();
    const out = (await tool.handler(
      { tickers: ["AAPL"], fields: ["hve_markers", "low_vol_markers"] },
      ctx,
    )) as Columnar;
    const row = out.rows[0];
    expect(row[1]).toBeNull();
    // Observed on the frozen 2026-09-18 AAPL fixture.
    expect(cell(out, row, "hve_markers")).toHaveLength(2);
    expect(cell(out, row, "low_vol_markers")).toHaveLength(108);
  });

  it("(q) the default column list is exactly the compact set", async () => {
    const tool = await loadTool();
    const { ctx } = makeCtx();
    const out = (await tool.handler({}, ctx)) as Columnar;
    // Literal copy of DEFAULT_FIELDS — a change to the compact set fails here.
    expect(out.columns).toEqual([
      "ticker",
      "error",
      "eod_as_of",
      "live_captured_at",
      "price",
      "z",
      "z_band",
      "dist_pct",
      "composite",
      "rsi14",
      "rv20",
      "macd_signal",
      "kinematics",
      "alignment",
      "ema5",
      "ema20",
      "ema50",
      "bb_upper",
      "bb_lower",
      "atr_upper",
      "atr_lower",
      "vol_ma50",
      "hve_last",
      "chanlun_last_point",
      "chanlun_last_zhongshu",
      "chanlun_points_n",
      "vp_poc",
      "vp_vah",
      "vp_val",
      "vp_nearest_s",
      "vp_nearest_r",
      "vp_bias",
      "fvg_n",
      "fvg_nearest",
      "ret_skew",
      "ret_sd",
    ]);
  });
});
