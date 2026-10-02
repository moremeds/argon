// technicals_scan — the whole Technicals surface as a columnar bulk tool. Same
// payloads the UI fetches, same pure functions (mergeLiveHead →
// technicalsOverlays → T1b verdicts/distribution/magnet helpers) — same inputs,
// same values. B-owned; the McpTool/ToolCtx/Columnar contracts live in
// ../types.ts and are not touched here.
import { z } from "zod";
import type { Columnar, McpTool, ToolCtx } from "../types";
import { makePool } from "../lib/pool";
import type {
  MagnetsResponse,
  TechnicalsLiveResponse,
  TechnicalsResponse,
} from "@/lib/api";
import { mergeLiveHead, type Timeframe } from "@/lib/technicals/series";
import {
  technicalsOverlays,
  type TechnicalsOverlays,
} from "@/lib/technicals/overlays";
import {
  alignmentBadge,
  kinematicsReading,
  macdSignalText,
  type DualMacdDetail,
} from "@/lib/technicals/verdicts";
import {
  returnDistribution,
  type ReturnDistribution,
} from "@/lib/technicals/returnDistribution";
import {
  kinematicsLeg,
  volumeTile,
  type KinematicsLeg,
  type VolumeTile,
} from "@/lib/magnetTiles";

// ── EOD cache ─────────────────────────────────────────────────────────────
// The /technicals payload is daily-bar history — static within a scan session
// until the nightly refresh (or an on-demand /technicals/refresh) rewrites
// technical_daily. The invalidation key is max(inserted_at); the upsert sets
// inserted_at = now() on conflict, so both paths move the key. Re-checked at
// most once per 60 s; a key change drops the whole map.
const EOD_CACHE = new Map<string, TechnicalsResponse>();
const KEY_TTL_MS = 60_000;
let eodKey: string | null = null;
let eodKeyAt = -Infinity;
let eodKeyInFlight: Promise<void> | null = null;

async function refreshEodKey(ctx: ToolCtx, now: number): Promise<void> {
  if (now - eodKeyAt < KEY_TTL_MS) return;
  // Single-flight: concurrent callers within the stale window share the one
  // pending key query instead of racing it.
  eodKeyInFlight ??= (async () => {
    const res = (await ctx.db.query(
      "SELECT max(inserted_at) AS k FROM uw_scan.technical_daily",
    )) as { rows?: { k: unknown }[] };
    const k = res?.rows?.[0]?.k;
    const key = k == null ? "" : String(k);
    if (key !== eodKey) EOD_CACHE.clear();
    eodKey = key;
    eodKeyAt = now;
  })().finally(() => {
    eodKeyInFlight = null;
  });
  await eodKeyInFlight;
}

// ── detail cast ───────────────────────────────────────────────────────────
// TechnicalsResponse.detail is { [key]: unknown } in the generated schema —
// the panels cast the same way.
type TechDetail = {
  rsi?: { rsi14?: number | null } | null;
  distribution?: { rv20?: number | null } | null;
  dual_macd?: DualMacdDetail | null;
  kinematics?: {
    sma20?: { tstat?: number | null } | null;
    sma50?: { tstat?: number | null } | null;
    sma200?: { tstat?: number | null } | null;
    alignment?: number | null;
  } | null;
};

type RowCtx = {
  eod: TechnicalsResponse;
  data: TechnicalsResponse; // merged EOD + live head
  ov: TechnicalsOverlays;
  dist: ReturnDistribution;
  det: TechDetail | null;
  liveCapturedAt: string | null; // set only when a fresh payload actually merged
  magnet: { tile: VolumeTile; leg: KinematicsLeg } | null;
};

const last = <T>(a: readonly T[]): T | null => a.at(-1) ?? null;

// The unfilled FVG nearest the last close — distance from the close to the
// gap's band (0 when price sits inside it).
function nearestGap(x: RowCtx) {
  const close = last(x.ov.rows)?.close;
  if (close == null || x.ov.fvg.gaps.length === 0) return null;
  const dist = (g: { top: number; bottom: number }) =>
    close > g.top ? close - g.top : close < g.bottom ? g.bottom - close : 0;
  return x.ov.fvg.gaps.reduce((best, g) => (dist(g) < dist(best) ? g : best));
}

// Canonical field order — "*" selects all of these; the default compact set is
// the first block.
const FIELD_GETTERS: Record<string, (x: RowCtx) => unknown> = {
  eod_as_of: (x) => x.eod.as_of ?? null,
  live_captured_at: (x) => x.liveCapturedAt,
  price: (x) => x.data.header?.price ?? null,
  z: (x) => x.data.header?.z ?? null,
  z_band: (x) => x.data.header?.z_band ?? null,
  dist_pct: (x) => x.data.header?.dist_pct ?? null,
  composite: (x) => x.data.header?.composite ?? null,
  rsi14: (x) => x.det?.rsi?.rsi14 ?? null,
  rv20: (x) => x.det?.distribution?.rv20 ?? null,
  macd_signal: (x) =>
    macdSignalText(x.det?.dual_macd ?? undefined)?.text ?? null,
  kinematics: (x) =>
    kinematicsReading(
      x.det?.kinematics?.sma20?.tstat,
      x.det?.kinematics?.sma50?.tstat,
      x.det?.kinematics?.sma200?.tstat,
    ),
  alignment: (x) => alignmentBadge(x.det?.kinematics?.alignment)?.text ?? null,
  ema5: (x) => x.ov.ema5.at(-1) ?? null,
  ema20: (x) => x.ov.ema20.at(-1) ?? null,
  ema50: (x) => x.ov.ema50.at(-1) ?? null,
  bb_upper: (x) => x.ov.bollinger.upper.at(-1) ?? null,
  bb_lower: (x) => x.ov.bollinger.lower.at(-1) ?? null,
  atr_upper: (x) => x.ov.atrBand.upper.at(-1) ?? null,
  atr_lower: (x) => x.ov.atrBand.lower.at(-1) ?? null,
  vol_ma50: (x) => x.ov.volMa50.at(-1) ?? null,
  hve_last: (x) => {
    const m = last(x.ov.markers.highVol);
    return m ? { time: m.time, text: m.text } : null;
  },
  chanlun_last_point: (x) => {
    const p = last(x.ov.chanlun.result.points);
    return p
      ? {
          time: p.time,
          type: p.kind,
          price: p.price,
          confirmed: p.confirmed,
          resonant: p.resonant ?? false,
        }
      : null;
  },
  chanlun_last_zhongshu: (x) => last(x.ov.chanlun.result.zhongshus),
  chanlun_points_n: (x) => x.ov.chanlun.result.points.length,
  vp_poc: (x) => x.ov.vp.stats?.poc ?? null,
  vp_vah: (x) => x.ov.vp.stats?.vah ?? null,
  vp_val: (x) => x.ov.vp.stats?.val ?? null,
  vp_nearest_s: (x) => x.ov.vp.stats?.nearestSupport ?? null,
  vp_nearest_r: (x) => x.ov.vp.stats?.nearestResistance ?? null,
  vp_bias: (x) => x.ov.vp.stats?.bias ?? null,
  fvg_n: (x) => x.ov.fvg.gaps.length,
  fvg_nearest: (x) => nearestGap(x),
  ret_skew: (x) => x.dist.skew,
  ret_sd: (x) => x.dist.sd,
  // — extra fields, by name or "*" —
  sma20: (x) => last(x.data.series ?? [])?.sma20 ?? null,
  sma50: (x) => last(x.data.series ?? [])?.sma50 ?? null,
  sma200: (x) => last(x.data.series ?? [])?.sma200 ?? null,
  rs_ratio: (x) => last(x.data.series ?? [])?.rs_ratio ?? null,
  detail: (x) => x.data.detail ?? null,
  forward_returns: (x) => x.data.forward_returns ?? null,
  vwap_anchor: (x) => x.data.vwap_anchor ?? null,
  macd_watchlist_pctile: (x) => x.data.macd_watchlist_pctile ?? null,
  chanlun: (x) => x.ov.chanlun.result,
  vp: (x) => ({
    profile: x.ov.vp.profile,
    zones: x.ov.vp.zones,
    lvn: x.ov.vp.lvn,
    stats: x.ov.vp.stats,
  }),
  fvg_gaps: (x) => x.ov.fvg.gaps,
  return_distribution: (x) => x.dist,
  // Magnet tile values — fetched per ticker only when a magnet_* field is on.
  magnet_vol_last: (x) => x.magnet?.tile.lastVol ?? null,
  magnet_vol_ma20: (x) => x.magnet?.tile.lastVolMa ?? null,
  magnet_vol_ratio: (x) => x.magnet?.tile.ratio ?? null,
  magnet_vol_bars: (x) => x.magnet?.tile.bars ?? null,
  magnet_velocity: (x) => x.magnet?.leg.v ?? null,
  magnet_accel: (x) => x.magnet?.leg.accel ?? null,
};

const ALL_FIELDS = Object.keys(FIELD_GETTERS);

// The compact set — one row of the UI's headline values. Everything above
// ret_sd is a default; the rest is reachable by name or "*".
const DEFAULT_FIELDS = [
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
];

const MAX_IN_FLIGHT = 8;
// Module-level on purpose: the handler's fan-out and standalone scanTicker
// calls share the same cap, so the internal API never sees more than
// MAX_IN_FLIGHT requests from this module at once.
const LIMIT = makePool(MAX_IN_FLIGHT);

function resolveFields(requested: string[] | undefined): string[] {
  if (requested == null) return [...DEFAULT_FIELDS];
  if (requested.includes("*")) return [...ALL_FIELDS];
  const bad = requested.filter((f) => !(f in FIELD_GETTERS));
  if (bad.length)
    throw new Error(
      `technicals_scan: unknown field(s) ${bad.join(", ")} — valid fields: ` +
        `${ALL_FIELDS.join(", ")} (or ["*"] for all)`,
    );
  return requested;
}

// Per-ticker pipeline shared by the handler fan-out and the exported
// scanTicker: EOD (cached) → live (never cached, failure → null) →
// mergeLiveHead → overlays/verdicts/distribution → magnets on demand.
// Throws on a hard failure; callers format the error row.
async function loadTicker(
  ctx: ToolCtx,
  ticker: string,
  opts: { now: number; timeframe: Timeframe; wantMagnet: boolean },
): Promise<RowCtx> {
  let eod = EOD_CACHE.get(ticker);
  if (!eod) {
    eod = (await LIMIT(() =>
      ctx.apiGet(`/stock/${ticker}/technicals`),
    )) as TechnicalsResponse;
    EOD_CACHE.set(ticker, eod);
  }
  const live = (await LIMIT(() =>
    ctx.apiGet(`/stock/${ticker}/technicals/live`),
  ).catch(() => null)) as TechnicalsLiveResponse | null;
  const data = mergeLiveHead(eod, live, opts.now);
  const ov = technicalsOverlays(data, opts.timeframe);
  const dist = returnDistribution(data.series ?? []);
  const det = (data.detail ?? null) as TechDetail | null;
  // mergeLiveHead returns the input object untouched when the live head is
  // stale — a new reference means a fresh payload actually merged.
  const liveCapturedAt = data !== eod ? (live?.captured_at ?? null) : null;
  let magnet: RowCtx["magnet"] = null;
  if (opts.wantMagnet) {
    const mg = (await LIMIT(() =>
      ctx.apiGet(`/stock/${ticker}/magnets`),
    )) as MagnetsResponse;
    magnet = {
      tile: volumeTile(mg.candles),
      leg: kinematicsLeg(mg.candles.map((c) => c.close)),
    };
  }
  return { eod, data, ov, dist, det, liveCapturedAt, magnet };
}

export type ScanTickerRow = { ticker: string; error: string | null } & Record<
  string,
  unknown
>;

// Single-ticker entry point for other tools (T3's ticker_snapshot reuses it).
// Same fields, same values as one columnar row from the tool handler — keys
// are ticker, error, then each requested field name. On failure the row is
// { ticker, error: message, <requested fields>: null }.
export async function scanTicker(
  ctx: ToolCtx,
  ticker: string,
  opts: { fields?: string[]; timeframe?: Timeframe } = {},
): Promise<ScanTickerRow> {
  const now = Date.now();
  const fields = resolveFields(opts.fields);
  const t = ticker.toUpperCase();
  await refreshEodKey(ctx, now);
  try {
    const x = await loadTicker(ctx, t, {
      now,
      timeframe: opts.timeframe ?? "1y",
      wantMagnet: fields.some((f) => f.startsWith("magnet_")),
    });
    return {
      ticker: t,
      error: null,
      ...Object.fromEntries(fields.map((f) => [f, FIELD_GETTERS[f](x)])),
    };
  } catch (e) {
    return {
      ticker: t,
      error: e instanceof Error ? e.message : String(e),
      ...Object.fromEntries(fields.map((f) => [f, null])),
    };
  }
}

const inputSchema = {
  tickers: z.array(z.string()).optional(),
  fields: z.array(z.string()).optional(),
  timeframe: z.enum(["full", "1y", "ytd", "3m"]).optional(),
};

export const tool: McpTool<typeof inputSchema> = {
  name: "technicals_scan",
  description:
    "Scan every active watchlist ticker — or the given `tickers` (upper-cased; " +
    "watchlist membership not required) — through the Technicals surface: the " +
    "internal /technicals EOD payload merged with /technicals/live via " +
    "mergeLiveHead, plus every browser-computed overlay via technicalsOverlays " +
    "(same functions, same values as the UI). Output is columnar " +
    "{ as_of: { eod, live }, columns, rows }; columns always start " +
    "ticker, error and a failed ticker's row carries error text with the other " +
    "columns null. Default fields: " +
    DEFAULT_FIELDS.join(", ") +
    '. fields: ["*"] selects every field; extras by name: ' +
    ALL_FIELDS.filter((f) => !DEFAULT_FIELDS.includes(f)).join(", ") +
    ". Cost: first call after the nightly technicals refresh fans out ~170×2 " +
    "internal GETs (≤8 in flight); later calls reuse the cached EOD layer and " +
    "refetch only the small live payloads; magnet_* fields add one GET per " +
    "ticker. `timeframe` (default 1y) affects only the FVG window.",
  inputSchema,
  handler: async (args, ctx): Promise<Columnar> => {
    const now = Date.now();
    const timeframe: Timeframe = args.timeframe ?? "1y";
    const fields = resolveFields(args.fields);

    const tickers =
      args.tickers != null
        ? args.tickers.map((t) => t.toUpperCase())
        : (((
            (await LIMIT(() => ctx.apiGet("/watchlist"))) as {
              tickers?: { ticker?: string }[];
            }
          ).tickers ?? []
        ).map((t) => t.ticker).filter((t): t is string => !!t));

    await refreshEodKey(ctx, now);
    const wantMagnet = fields.some((f) => f.startsWith("magnet_"));

    type Row = {
      cells: unknown[];
      eodAsOf: string | null;
      liveCapturedAt: string | null;
    };
    const rows = await Promise.all(
      tickers.map(async (ticker): Promise<Row> => {
        try {
          const x = await loadTicker(ctx, ticker, {
            now,
            timeframe,
            wantMagnet,
          });
          return {
            cells: [ticker, null, ...fields.map((f) => FIELD_GETTERS[f](x))],
            eodAsOf: x.eod.as_of ?? null,
            liveCapturedAt: x.liveCapturedAt,
          };
        } catch (e) {
          return {
            cells: [
              ticker,
              e instanceof Error ? e.message : String(e),
              ...fields.map(() => null),
            ],
            eodAsOf: null,
            liveCapturedAt: null,
          };
        }
      }),
    );
    const maxStr = (vals: (string | null)[]) =>
      vals.reduce<string | null>(
        (a, b) => (a == null ? b : b == null ? a : a > b ? a : b),
        null,
      );
    return {
      as_of: {
        eod: maxStr(rows.map((r) => r.eodAsOf)),
        live: maxStr(rows.map((r) => r.liveCapturedAt)),
      },
      columns: ["ticker", "error", ...fields],
      rows: rows.map((r) => r.cells),
    };
  },
};
