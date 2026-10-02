// Greeks-panel derivations shared by CharmPanel and VannaPanel (they carry
// identical local copies): expiry sort, default expiry pick, per-strike
// net = call + put for that expiry, and the |net| < 1000 → "muted" tone.
import type { components } from "@/lib/types";

export type StrikeExposureRow = components["schemas"]["StrikeExposureRow"];
export type ExposuresSummaryRow =
  components["schemas"]["ExposuresSummaryRow"];
export type GreekKind = "charm" | "vanna";

// The panels' own local toNum, kept verbatim: unlike lib/formatters.toNum it
// maps "" to 0 (Number("") === 0), so an empty strike plots at 0. Using the
// formatters version here would change a rendered value.
const toNum = (v: string | number | null | undefined): number | null => {
  if (v == null) return null;
  const n = typeof v === "number" ? v : Number(v);
  return Number.isFinite(n) ? n : null;
};

/** Expiry-ascending copy of the summary rows (verbatim). */
export function sortByExpiry(
  summary: ExposuresSummaryRow[],
): ExposuresSummaryRow[] {
  return [...summary].sort((a, b) => (a.expiry < b.expiry ? -1 : 1));
}

/** First live expiry (dte null or ≥ 0, smallest dte), else the earliest. */
export function defaultExpiry(
  sortedSummary: ExposuresSummaryRow[],
): string | null {
  const live = sortedSummary
    .filter((r) => r.dte == null || (r.dte as number) >= 0)
    .sort(
      (a, b) => ((a.dte ?? 99999) as number) - ((b.dte ?? 99999) as number),
    );
  return (live[0] ?? sortedSummary[0])?.expiry ?? null;
}

/** Per-strike net = call + put for the given greek, strike-ascending. */
export function netExposureCurve(
  rows: StrikeExposureRow[],
  kind: GreekKind,
): { strike: number; netValue: number }[] {
  const callField = kind === "charm" ? "call_charm" : "call_vanna";
  const putField = kind === "charm" ? "put_charm" : "put_vanna";
  return rows
    .map((r) => ({
      strike: toNum(r.strike) ?? NaN,
      netValue: (toNum(r[callField]) ?? 0) + (toNum(r[putField]) ?? 0),
    }))
    .filter((p) => Number.isFinite(p.strike))
    .sort((a, b) => a.strike - b.strike);
}

/** |net| < 1000 (or missing) → "muted". */
export function netExposureTone(
  net: number | null,
): "muted" | "negative" | "positive" {
  return net == null || Math.abs(net) < 1000
    ? "muted"
    : net < 0
      ? "negative"
      : "positive";
}
