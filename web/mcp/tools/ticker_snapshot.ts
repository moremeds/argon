// ticker_snapshot — one call → every per-ticker snapshot section, reusing the
// same pure derivations the UI renders (web/lib/snapshot) and the T2
// technicals_scan per-ticker path. Section failures are isolated: a failed
// section returns { error } and never fails the call.
import { z } from "zod";
import type { McpTool, ToolCtx } from "../types";
import { normalizeTicker, TICKER_RE } from "../lib/ticker";
import { scanTicker } from "./technicals_scan";
import type {
  CockpitDealerResponse,
  CockpitStateResponse,
  CockpitVrpResponse,
  SingleStockReport,
  TradeInsightsResponse,
} from "@/lib/api";
import { toNum } from "@/lib/formatters";
import { chainFlowRead } from "@/lib/snapshot/chainFlow";
import {
  groupByExpiry,
  peaks,
  totals,
} from "@/lib/snapshot/cockpitDealer";
import { vrpBand, vrpStats, vrpZ } from "@/lib/snapshot/cockpitVrp";
import { flowTimelineSeries } from "@/lib/snapshot/flowTimeline";
import { gammaBarTiles } from "@/lib/snapshot/gammaBar";
import {
  defaultExpiry,
  netExposureCurve,
  netExposureTone,
  sortByExpiry,
} from "@/lib/snapshot/greeksNet";
import { termMoveRead } from "@/lib/snapshot/termMove";

// Mirrors web/app/cockpit/[ticker]/page.tsx — cockpit data exists only for
// these tickers; for anything else the cockpit section is exactly null.
const COCKPIT_TICKERS = new Set(["SPX", "SPY", "QQQ", "IWM"]);

type Section = Record<string, unknown>;

const ok = <T>(value: T): { value: T } => ({ value });

async function section<T>(p: Promise<T>): Promise<{ value?: T; error?: string }> {
  try {
    return ok(await p);
  } catch (e) {
    return { error: e instanceof Error ? e.message : String(e) };
  }
}

const err = (e: string | undefined): Section => ({ error: e ?? "unknown error" });

function technicalsSection(row: Record<string, unknown>): Section {
  if (row.error) return err(String(row.error));
  const rest = { ...row };
  delete rest.error;
  return {
    as_of: { eod: row.eod_as_of ?? null, live: row.live_captured_at ?? null },
    ...rest,
  };
}

function chainFlowSection(p: TradeInsightsResponse): Section {
  return { as_of: p.as_of ?? null, ...chainFlowRead(p.flow_table ?? []) };
}

function termMoveSection(p: TradeInsightsResponse): Section {
  return { as_of: p.as_of ?? null, ...termMoveRead(p.term_structure_table ?? []) };
}

function flowTimelineSection(p: SingleStockReport): Section {
  return { as_of: p.generated_at ?? null, ...flowTimelineSeries(p.options_timeline ?? []) };
}

function gammaBarSection(p: SingleStockReport): Section {
  return { as_of: p.generated_at ?? null, ...gammaBarTiles(p) };
}

function greekSection(p: SingleStockReport, kind: "charm" | "vanna"): Section {
  const sorted = sortByExpiry(p.exposures_summary ?? []);
  const expiry = defaultExpiry(sorted);
  const summaryRow =
    sorted.find((r) => r.expiry === expiry) ?? sorted[0] ?? null;
  const rowsForExpiry = (p.strike_exposures ?? []).filter(
    (r) => r.expiry === summaryRow?.expiry,
  );
  const net = toNum(kind === "charm" ? summaryRow?.net_charm : summaryRow?.net_vanna);
  const base: Section = {
    as_of: p.generated_at ?? null,
    expiry: expiry ?? summaryRow?.expiry ?? null,
    dte: summaryRow?.dte ?? null,
    spot: toNum(summaryRow?.spot),
    net,
    tone: netExposureTone(net),
    flip: toNum(kind === "charm" ? summaryRow?.charm_flip : summaryRow?.vanna_flip),
    curve: netExposureCurve(rowsForExpiry, kind),
  };
  if (kind === "charm") {
    base.pin_strike = toNum(summaryRow?.charm_pin_strike);
    base.imbalance_pct = toNum(summaryRow?.charm_imbalance_pct);
    base.above_sum = toNum(summaryRow?.charm_above_sum);
    base.below_sum = toNum(summaryRow?.charm_below_sum);
  } else {
    base.top_strike = toNum(summaryRow?.top_vanna_strike);
    base.top_value = toNum(summaryRow?.top_vanna_value);
    base.regime = summaryRow?.vanna_regime ?? null;
  }
  return base;
}

function cockpitSection(
  vrp: CockpitVrpResponse,
  dealer: CockpitDealerResponse,
  stateResp: CockpitStateResponse | null,
): Section {
  const points = vrp.points ?? [];
  const stats = vrpStats(points);
  const band = vrpBand(stats);
  const latest = points[points.length - 1] ?? null;
  const dealerPoints = dealer.points ?? [];
  const groups = groupByExpiry(dealerPoints).slice(0, 6);
  const primary = groups[0] ?? null;
  const primaryPoints = primary?.[1] ?? [];
  return {
    as_of:
      stateResp?.state?.market_date ??
      vrp.market_date ??
      dealer.market_date ??
      null,
    vrp: {
      points_n: points.length,
      stats,
      band: band ?? null,
      latest: latest
        ? {
            market_date: latest.market_date ?? null,
            iv: toNum(latest.iv),
            rv: toNum(latest.rv),
            vrp: toNum(latest.vrp),
            iv_rank_1y: toNum(latest.iv_rank_1y),
            z: vrpZ(toNum(latest.vrp), stats),
          }
        : null,
    },
    dealer: {
      groups_n: groups.length,
      expiries: groups.map(([expiry]) => expiry),
      primary_expiry: primary?.[0] ?? null,
      points_n: dealerPoints.length,
      totals: totals(primaryPoints),
      peaks: peaks(primaryPoints),
    },
    // State pass-through: the cockpit UI renders these fields verbatim.
    state: stateResp?.state ?? null,
  };
}

const inputSchema = {
  ticker: z
    .string()
    .min(1)
    .regex(TICKER_RE)
    .describe("Ticker symbol (upper-cased automatically), e.g. SPY"),
};

export const tool: McpTool<typeof inputSchema> = {
  name: "ticker_snapshot",
  description:
    "Per-ticker snapshot: every derivation the stock page renders, in one call. " +
    "Sections: technicals (the full technicals_scan row), chain_flow (call/put " +
    "tape read), term_move (term-structure implied moves), flow_timeline " +
    "(daily volume/OI + put/call ratios), gamma_bar (dealer Γ tiles), charm " +
    "and vanna (per-strike net Greeks for the default expiry). A failed " +
    "section returns { error } without failing the call. " +
    "Cockpit sections (VRP stats/band/z, dealer vanna/charm totals and peaks, " +
    "state pass-through) exist only for SPX, SPY, QQQ and IWM; for other " +
    "tickers `cockpit` is null.",
  inputSchema,
  handler: async (args, ctx: ToolCtx) => {
    const T = normalizeTicker(args.ticker);
    // Path segments are normalized already; encodeURIComponent is defence in
    // depth for anything that slips past the charset.
    const E = encodeURIComponent(T);
    const cockpitGated = COCKPIT_TICKERS.has(T);

    const technicalsP = section(
      scanTicker(ctx, T, { fields: ["*"], timeframe: "1y" }),
    );
    const tradeInsightsP = section(
      ctx.apiGet(`/stock/${E}/trade-insights`) as Promise<TradeInsightsResponse>,
    );
    const stockP = section(
      ctx.apiGet(`/stock/${E}`) as Promise<SingleStockReport>,
    );
    const cockpitP = cockpitGated
      ? section(
          Promise.all([
            ctx.apiGet(`/cockpit/${E}/vrp`) as Promise<CockpitVrpResponse>,
            ctx.apiGet(`/cockpit/${E}/dealer`) as Promise<CockpitDealerResponse>,
            ctx.apiGet(
              `/cockpit/${E}/state`,
            ) as Promise<CockpitStateResponse | null>,
          ]),
        )
      : null;

    const [technicals, tradeInsights, stock] = await Promise.all([
      technicalsP,
      tradeInsightsP,
      stockP,
    ]);
    const cockpit = cockpitP ? await cockpitP : null;

    let cockpitOut: Section | null = null;
    if (cockpitGated && cockpit) {
      cockpitOut = cockpit.value
        ? cockpitSection(cockpit.value[0], cockpit.value[1], cockpit.value[2])
        : err(cockpit.error);
    }

    const stockOk = stock.value;
    return {
      ticker: T,
      technicals: technicals.value
        ? technicalsSection(technicals.value as Record<string, unknown>)
        : err(technicals.error),
      chain_flow: tradeInsights.value
        ? chainFlowSection(tradeInsights.value)
        : err(tradeInsights.error),
      term_move: tradeInsights.value
        ? termMoveSection(tradeInsights.value)
        : err(tradeInsights.error),
      flow_timeline: stockOk ? flowTimelineSection(stockOk) : err(stock.error),
      gamma_bar: stockOk ? gammaBarSection(stockOk) : err(stock.error),
      charm: stockOk ? greekSection(stockOk, "charm") : err(stock.error),
      vanna: stockOk ? greekSection(stockOk, "vanna") : err(stock.error),
      cockpit: cockpitOut,
    };
  },
};
