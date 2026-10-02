// Term-structure / implied-move derivations, verbatim from
// components/stock/panels/TermMovePanel.tsx. The narrative termRead stays in
// the component (it embeds %-formatted strings); this returns the rows and
// numbers it renders.
import type { TradeInsightsResponse } from "@/lib/api";

export type TermRow = TradeInsightsResponse["term_structure_table"][number];

// Component-local helper moved with the derivation: nullish → null, no
// finite-check (unlike toNum which also rejects "" and non-finite).
const n = (v: string | number | null | undefined) =>
  v == null ? null : Number(v);

export type TermMoveRead = {
  /** Rows sorted by DTE ascending (null DTE sorts last, as 9999). */
  byExpiry: TermRow[];
  /** Lowest-DTE row; undefined when rows is empty. */
  front: TermRow | undefined;
  /** First row with a different expiry than front; null if none. */
  back: TermRow | null;
  /** Row with the max daily_implied_move_perc. */
  highestDaily: TermRow | undefined;
  frontDaily: number | null;
  backDaily: number | null;
  curveRead: "Front elevated" | "Back elevated" | "Flat / unclear";
  highlightedCount: number;
  highlightedRows: TermRow[];
};

export function termMoveRead(rows: TermRow[]): TermMoveRead {
  const byExpiry = [...rows].sort((a, b) => {
    const aDte = a.dte ?? 9999;
    const bDte = b.dte ?? 9999;
    return aDte - bDte;
  });
  const front = byExpiry[0];
  const back = byExpiry.find((row) => row.expiry !== front?.expiry) ?? null;
  const highestDaily = [...rows].sort(
    (a, b) =>
      (n(b.daily_implied_move_perc) ?? -1) -
      (n(a.daily_implied_move_perc) ?? -1),
  )[0];
  const frontDaily = front ? n(front.daily_implied_move_perc) : null;
  const backDaily = back ? n(back.daily_implied_move_perc) : null;
  const curveRead =
    frontDaily != null && backDaily != null && frontDaily > backDaily
      ? ("Front elevated" as const)
      : frontDaily != null && backDaily != null && frontDaily < backDaily
        ? ("Back elevated" as const)
        : ("Flat / unclear" as const);
  const highlightedCount = Math.min(rows.length, 6);
  const highlightedRows = byExpiry.slice(0, highlightedCount);
  return {
    byExpiry,
    front,
    back,
    highestDaily,
    frontDaily,
    backDaily,
    curveRead,
    highlightedCount,
    highlightedRows,
  };
}
