// regime_state — one call → the /regime page's state, reusing the same pure
// derivations the UI renders (web/lib/regime/derive). /regime/quotes is
// fetched once and shared by the GEX and vol-backdrop sections; a failed
// section returns { error } and never fails the call.
import type { McpTool, ToolCtx } from "../types";
import type { components } from "@/lib/types";
import type { GexData } from "@/lib/regime/useGex";
import type { VolBackdropData } from "@/lib/regime/useVolBackdrop";
import type { RegimeQuotesResponse } from "@/lib/regime/useRegimeQuotes";
import type { CriLiveResponse } from "@/lib/regime/useCriLive";
import type { CriDailyEntry } from "@/lib/regime/useCriSeries";
import {
  gexSpotRead,
  liveSpotSelection,
  retagProfileForSpot,
} from "@/lib/regime/derive/gex";
import {
  symbolRead,
  termStructureRead,
  VOL_BACKDROP_SYMBOLS,
} from "@/lib/regime/derive/volBackdrop";
import {
  priorComponentScore,
  priorHistoryRow,
  spxMedianFiltered,
  vixDelta3dSeries,
} from "@/lib/regime/derive/cri";
import type { ComponentSlot } from "@/components/regime/primitives/ComponentBar";

type VcgResponse = components["schemas"]["VcgResponse"];
type VcgLiveResponse = components["schemas"]["VcgLiveResponse"];
type VrpMacroSignalResponse =
  components["schemas"]["VrpMacroSignalResponse"];
type VrpMacroSignalLiveResponse =
  components["schemas"]["VrpMacroSignalLiveResponse"];
type CriDailyHistoryResponse =
  components["schemas"]["CriDailyHistoryResponse"];
type VrpMacroSignalRow = components["schemas"]["VrpMacroSignalRow"];

type Section = Record<string, unknown>;

const err = (e: string | undefined): Section => ({
  error: e ?? "unknown error",
});

async function section<T>(p: Promise<T>): Promise<{ value?: T; error?: string }> {
  try {
    return { value: await p };
  } catch (e) {
    return { error: e instanceof Error ? e.message : String(e) };
  }
}

const SLOTS: ComponentSlot[] = ["vix", "vvix", "correlation", "momentum"];

function gexSection(
  data: GexData,
  quotes: RegimeQuotesResponse | null,
  now: number,
): Section {
  const { liveSpot } = liveSpotSelection(
    data.ticker,
    data.tape_time,
    quotes,
    now,
  );
  const { displaySpot, dayChange, dayChangePct } = gexSpotRead(data, liveSpot);
  return {
    as_of: data.scan_time ?? null,
    spot: data.spot,
    live_spot: liveSpot,
    display_spot: displaySpot,
    day_change: dayChange,
    day_change_pct: dayChangePct,
    levels: data.levels ?? null,
    flip: data.levels?.gex_flip ?? null,
    // The UI retags only on a live spot (liveProfile useMemo); else the
    // payload's own tags stand.
    profile:
      liveSpot != null
        ? retagProfileForSpot(data.profile ?? [], liveSpot, data.levels)
        : (data.profile ?? []),
  };
}

function volBackdropSection(
  data: VolBackdropData,
  quotes: RegimeQuotesResponse | null,
  now: number,
): Section {
  const { ratio, state, ratioSource } = termStructureRead(data, quotes, now);
  const symbols = Object.fromEntries(
    VOL_BACKDROP_SYMBOLS.map((s) => {
      const { live, close, chg } = symbolRead(s, data, quotes, now);
      return [s, { live, last: close, change_pct: chg }];
    }),
  );
  return {
    as_of: data.as_of ?? null,
    ratio,
    state,
    ratio_source: ratioSource,
    symbols,
  };
}

function criSection(
  live: CriLiveResponse,
  history: CriDailyHistoryResponse,
): Section {
  const prior = priorHistoryRow(live);
  const rows = (history.rows ?? []) as CriDailyEntry[];
  const vixDelta3d = vixDelta3dSeries(rows);
  const spxFiltered = spxMedianFiltered(rows);
  return {
    as_of: live.scan_time ?? live.date ?? null,
    basis: live.basis ?? null,
    score: live.cri?.score ?? null,
    level: live.cri?.level ?? null,
    composite_version: live.cri?.composite_version ?? null,
    components: live.cri?.components ?? null,
    prior_components: Object.fromEntries(
      SLOTS.map((slot) => [slot, priorComponentScore(prior, slot)]),
    ),
    // The tiles render the live payload's own fields — data.vix_delta_3d and
    // data.spy under the data.spx_source label — not the last value of the
    // 90d history-derived series.
    vix_delta_3d: live.vix_delta_3d ?? null,
    spy: live.spy ?? null,
    spx_source: live.spx_source ?? null,
    // The history-derived series are kept because the page renders them as
    // the tiles' in-card sparklines; named as series so they can't be read
    // as the tile scalars.
    vix_delta_3d_series: vixDelta3d,
    spx_filtered_series: spxFiltered.series,
    history_as_of: rows.length ? (rows[rows.length - 1].date ?? null) : null,
  };
}

/** Pass-through of the VCG state payload, minus the bulky history array. */
function vcgSection(p: VcgResponse | VcgLiveResponse): Section {
  const rest = { ...p };
  delete rest.history;
  return {
    as_of: p.scan_time ?? p.date ?? null,
    basis: "basis" in p ? (p.basis ?? null) : null,
    ...rest,
  };
}

/** Pass-through of the VRP macro-signal payload (live or EOD shape). */
function vrpMacroSection(
  p: VrpMacroSignalLiveResponse | VrpMacroSignalResponse,
): Section {
  // The payload carries no top-level timestamp; snapshot_date on each row is
  // when the job ran (as_of inside the row is the vol-data date).
  const rows: (VrpMacroSignalRow | null | undefined)[] =
    (p as VrpMacroSignalResponse).signals != null
      ? (p as VrpMacroSignalResponse).signals!
      : [(p as VrpMacroSignalLiveResponse).signal];
  const snapshot = rows
    .map((r) => r?.snapshot_date)
    .filter((d): d is string => d != null)
    .sort()
    .at(-1);
  return {
    as_of: snapshot ?? null,
    basis: "basis" in p ? (p.basis ?? null) : null,
    ...p,
  };
}

const inputSchema = {};

export const tool: McpTool<typeof inputSchema> = {
  name: "regime_state",
  description:
    "Cross-section /regime state in one call: gex (levels, flip, spot + live " +
    "SPX splice, day change, retagged profile), vol_backdrop (live VIX/VIX3M " +
    "term-structure ratio or EOD fallback, per-symbol last + % change for " +
    "VIX/VIX3M/VVIX/COR1M), cri (current score/level/components + basis, " +
    "prior-day component scores, the payload's vix_delta_3d + spy/spx_source " +
    "tile values, and the 90d VIX-Δ3d / median-filtered-SPX sparkline " +
    "series), vcg " +
    "and vrp_macro (live payload, falling back to the EOD snapshot when live " +
    "is unavailable). /regime/quotes is fetched once and shared. A failed " +
    "section returns { error } without failing the call.",
  inputSchema,
  handler: async (_args, ctx: ToolCtx) => {
    const now = Date.now();
    const quotesP = section(
      ctx.apiGet("/regime/quotes") as Promise<RegimeQuotesResponse>,
    );
    const gexP = section(ctx.apiGet("/regime/gex", { ticker: "SPX" }) as Promise<GexData>);
    const backdropP = section(
      ctx.apiGet("/regime/vol-backdrop") as Promise<VolBackdropData>,
    );
    const criLiveP = section(
      ctx.apiGet("/regime/cri/live") as Promise<CriLiveResponse>,
    );
    const criHistP = section(
      ctx.apiGet("/regime/cri/history", {
        days: 90,
      }) as Promise<CriDailyHistoryResponse>,
    );
    const vcgP = section(
      (ctx.apiGet("/regime/vcg/live") as Promise<VcgLiveResponse>).catch(() =>
        ctx.apiGet("/regime/vcg"),
      ) as Promise<VcgResponse | VcgLiveResponse>,
    );
    const vrpP = section(
      (
        ctx.apiGet("/regime/vrp-macro-signal/live") as Promise<VrpMacroSignalLiveResponse>
      ).catch(() => ctx.apiGet("/regime/vrp-macro-signal")) as Promise<
        VrpMacroSignalLiveResponse | VrpMacroSignalResponse
      >,
    );

    const [quotes, gex, backdrop, criLive, criHist, vcg, vrp] =
      await Promise.all([quotesP, gexP, backdropP, criLiveP, criHistP, vcgP, vrpP]);

    // A failed quotes call degrades both dependent sections to EOD inputs —
    // the same "no live quote" path the UI renders — rather than erroring.
    const q = quotes.value ?? null;
    return {
      gex: gex.value ? gexSection(gex.value, q, now) : err(gex.error),
      vol_backdrop: backdrop.value
        ? volBackdropSection(backdrop.value, q, now)
        : err(backdrop.error),
      cri:
        criLive.value && criHist.value
          ? criSection(criLive.value, criHist.value)
          : err(criLive.error ?? criHist.error),
      vcg: vcg.value ? vcgSection(vcg.value) : err(vcg.error),
      vrp_macro: vrp.value ? vrpMacroSection(vrp.value) : err(vrp.error),
    };
  },
};
