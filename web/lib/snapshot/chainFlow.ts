// Chain/flow read derivations, verbatim from
// components/stock/panels/ChainFlowReadPanel.tsx (the totals, tape ratio,
// busiest-strike pick, top-8 highlight ordering, t1 count, and read strings).
import type { TradeInsightsResponse } from "@/lib/api";

export type ChainFlowRow = TradeInsightsResponse["flow_table"][number];

// Component-local helper moved with the derivation: coerce nullish → 0 (unlike
// toNum which returns null).
const n = (v: string | number | null | undefined) =>
  v == null ? 0 : Number(v);

export type ChainFlowRead = {
  totalCallVolume: number;
  totalPutVolume: number;
  /** Σ call vol / Σ put vol; null when put volume is 0. */
  tapeRatio: number | null;
  t1Count: number;
  /** Busiest strike row = max(call vol + put vol + call OI + put OI). */
  strongest: ChainFlowRow | undefined;
  /** Top 8 by call+put volume, t1-flagged rows boosted +100000. */
  highlightedRows: ChainFlowRow[];
  flowRead: string;
  activityRead: string;
  confirmationRead: string;
};

export function chainFlowRead(rows: ChainFlowRow[]): ChainFlowRead {
  const totalCallVolume = rows.reduce(
    (sum, row) => sum + n(row.call_volume),
    0,
  );
  const totalPutVolume = rows.reduce((sum, row) => sum + n(row.put_volume), 0);
  const tapeRatio =
    totalPutVolume > 0 ? totalCallVolume / totalPutVolume : null;
  const t1Count = rows.filter(
    (row) => row.requires_t1_oi_confirmation,
  ).length;
  const strongest = [...rows].sort(
    (a, b) =>
      n(b.call_volume) +
      n(b.put_volume) +
      n(b.call_open_interest) +
      n(b.put_open_interest) -
      (n(a.call_volume) +
        n(a.put_volume) +
        n(a.call_open_interest) +
        n(a.put_open_interest)),
  )[0];
  const highlightedRows = [...rows]
    .sort((a, b) => {
      const bScore =
        n(b.call_volume) +
        n(b.put_volume) +
        (b.requires_t1_oi_confirmation ? 100000 : 0);
      const aScore =
        n(a.call_volume) +
        n(a.put_volume) +
        (a.requires_t1_oi_confirmation ? 100000 : 0);
      return bScore - aScore;
    })
    .slice(0, 8);
  const flowRead =
    tapeRatio == null
      ? "Put volume is unavailable, so call/put balance is inconclusive."
      : tapeRatio >= 1.2
        ? `Calls traded ${tapeRatio.toFixed(2)}x puts across available rows, so flow leans call-heavy.`
        : tapeRatio <= 0.8
          ? `Calls traded ${tapeRatio.toFixed(2)}x puts across available rows, so flow leans put-heavy.`
          : `Call and put volume are roughly balanced at ${tapeRatio.toFixed(2)}x.`;
  const activityRead = strongest
    ? `The busiest strike is ${strongest.strike}, which is the first place to inspect for pinning or crowding.`
    : "No single strike stands out from the available rows.";
  const confirmationRead =
    t1Count > 0
      ? `${t1Count} strike${t1Count === 1 ? " needs" : "s need"} next-day OI confirmation before treating volume as new positioning.`
      : "No highlighted strikes need next-day OI confirmation.";

  return {
    totalCallVolume,
    totalPutVolume,
    tapeRatio,
    t1Count,
    strongest,
    highlightedRows,
    flowRead,
    activityRead,
    confirmationRead,
  };
}
