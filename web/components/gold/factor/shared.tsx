import type { components } from "@/lib/types";

export type GoldFactor = components["schemas"]["GoldFactorResponse"];
export type FactorPoint = components["schemas"]["GoldFactorPoint"];
export type FactorYear = components["schemas"]["GoldFactorYear"];

/** One line on every research panel. The study described the past and its direction test
 *  failed; the label says so where the numbers are, not once at the top of the page. */
export const RESEARCH_LABEL =
  "Historical description, not a forecast · the direction test (Phase 3) failed";

/** The four parts and the remainder, in the order the breakdown charts stack them. */
export const PARTS = [
  {
    key: "real_yield_part",
    label: "Real yield",
    color: "var(--positive, #05ad98)",
  },
  { key: "dollar_part", label: "Dollar", color: "var(--warning, #f5a623)" },
  { key: "haven_part", label: "Safe haven", color: "var(--info, #8b5cf6)" },
  {
    key: "own_trailing_drift",
    label: "Last year's pace",
    color: "var(--text-muted, #64748b)",
  },
  {
    key: "unexplained_1",
    label: "Unexplained",
    color: "var(--text-secondary, #94a3b8)",
  },
] as const;

export type PartKey = (typeof PARTS)[number]["key"];

export const LABEL_TEXT: Record<string, string> = {
  much: "the three factors explain much",
  part: "the three factors explain part",
  little: "the three factors explain little",
};

export function fmt(v: number, digits = 2): string {
  const s = v.toFixed(digits);
  return v > 0 ? `+${s}` : s;
}

/** Rows with every part, so a sum over them adds up to gold's change exactly. */
export function complete(points: FactorPoint[]): FactorPoint[] {
  return points.filter((p) => PARTS.every((s) => p[s.key] != null));
}

export function sumParts(
  rows: FactorPoint[],
): Record<PartKey | "gold_change", number> {
  const out = { gold_change: 0 } as Record<PartKey | "gold_change", number>;
  for (const s of PARTS) out[s.key] = 0;
  for (const r of rows) {
    out.gold_change += r.gold_change;
    for (const s of PARTS) out[s.key] += r[s.key] ?? 0;
  }
  return out;
}
