import { z } from "zod";
import type { Columnar, McpTool, ToolCtx } from "../types";
import type { components } from "@/lib/types";
import { orderCards } from "@/lib/watchlist/cardOrder";

type WatchlistResponse = components["schemas"]["WatchlistResponse"];
type WatchlistChainsResponse =
  components["schemas"]["WatchlistChainsResponse"];

// Card field order mirrors the landing-page card. Values pass through
// verbatim — the server already computed spot, iv, returns, etc.
const COLUMNS = [
  "ticker",
  "sector",
  "group",
  "chains",
  "pinned",
  "hot",
  "spot",
  "spot_quoted_at",
  "iv_atm",
  "iv_rank",
  "market_cap",
  "aum",
  "setup",
  "aggression_pct",
  "returns",
  "gamma",
  "skew",
  "positioning",
] as const;

async function fetchChains(ctx: ToolCtx) {
  try {
    const p = (await ctx.apiGet(
      "/watchlist/chains",
    )) as WatchlistChainsResponse | null;
    return { chains: p?.chains ?? [] };
  } catch (e) {
    return { chains: [], chains_error: e instanceof Error ? e.message : String(e) };
  }
}

const inputSchema = {
  columns: z
    .array(z.enum(COLUMNS))
    .min(1)
    .optional()
    .describe("Return only these columns (ticker is always kept). Omit for all."),
  tickers: z
    .array(z.string().min(1))
    .min(1)
    .optional()
    .describe("Return only these tickers (upper-cased); landing-page order is kept."),
};

export const tool: McpTool<typeof inputSchema> = {
  name: "market_overview",
  description:
    "Watchlist card grid for the landing page. Columns: ticker, sector, " +
    "group (sector-group key), chains, pinned, hot, spot, spot_quoted_at, " +
    "iv_atm, iv_rank, market_cap, aum, setup, aggression_pct, returns, " +
    "gamma, skew, positioning — all card numbers are verbatim server " +
    "values, and the row order equals the landing page's grid order " +
    "(pinned first, then size within each sector; priority sectors first). " +
    "Also returns the filter-rail chains, scheduler_lag_seconds, and the " +
    "scan queue summary. Full response is ~95 KB for ~170 tickers; pass " +
    "`columns` (ticker is always kept; a one-column call is 6-13 KB, except " +
    "gamma ~32 KB and positioning ~22 KB) and/or `tickers` to narrow it.",
  inputSchema,
  handler: async (args, ctx) => {
    // Same split as lib/dashboardData.ts: the rail is chrome, the grid is the
    // page — a chains failure degrades to chains: [] + chains_error, while a
    // watchlist failure propagates as the tool error.
    const chainsP = fetchChains(ctx);
    const data = (await ctx.apiGet("/watchlist")) as WatchlistResponse;

    const only = args.tickers
      ? new Set(args.tickers.map((t) => t.trim().toUpperCase()))
      : null;
    const ordered = orderCards(data.tickers ?? []).filter(
      ({ card }) => !only || only.has(card.ticker),
    );
    const columns = args.columns
      ? COLUMNS.filter((c) => c === "ticker" || args.columns!.includes(c))
      : [...COLUMNS];
    const keep = columns.map((c) => COLUMNS.indexOf(c));
    const fullRows = ordered.map(({ card, group }) => [
      card.ticker,
      card.sector,
      group,
      card.chains,
      card.pinned,
      card.hot,
      card.spot,
      card.spot_quoted_at,
      card.iv_atm,
      card.iv_rank,
      card.market_cap,
      card.aum,
      card.setup,
      card.aggression_pct,
      card.returns,
      card.gamma,
      card.skew,
      card.positioning,
    ]);
    const rows = args.columns ? fullRows.map((r) => keep.map((i) => r[i])) : fullRows;

    const live = ordered.reduce<string | null>(
      (m, { card }) =>
        card.spot_quoted_at &&
        (!m || Date.parse(card.spot_quoted_at) > Date.parse(m))
          ? card.spot_quoted_at
          : m,
      null,
    );

    const out: Columnar & {
      chains: unknown[];
      scheduler_lag_seconds: number | null;
      queue: unknown;
      chains_error?: string;
    } = {
      as_of: { eod: data.scanned_at_max ?? null, live },
      columns,
      rows,
      ...(await chainsP),
      scheduler_lag_seconds: data.scheduler_lag_seconds ?? null,
      queue: data.queue ?? null,
    };
    return out;
  },
};
