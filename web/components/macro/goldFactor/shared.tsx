import type { components } from "@/lib/types";

export type GoldFactor = components["schemas"]["GoldFactorResponse"];
export type FactorPoint = components["schemas"]["GoldFactorPoint"];
export type FactorYear = components["schemas"]["GoldFactorYear"];
export type GoldFlows = components["schemas"]["GoldFlowsResponse"];

/** One line on every research panel. The study described the past and its direction test
 *  failed; the label says so where the numbers are, not once at the top of the page. */
export const RESEARCH_LABEL =
  "Describes the past, not a forecast · the direction test (Phase 3) failed";

export const SOURCE = "/api/gold/factor · gold_factor_daily";

/** Colours of the parts, their sum and gold itself (`.board` tokens in board.css). */
export const COLOR = {
  yield: "var(--f-yield)",
  dollar: "var(--f-dollar)",
  haven: "var(--f-haven)",
  drift: "var(--f-drift)",
  u: "var(--f-u)",
  sum: "var(--f-sum)",
  gold: "var(--f-gold)",
} as const;

/** The three factors, then the two remaining parts, in the order the charts stack them. */
export const PARTS = [
  { key: "real_yield_part", label: "Real yield", color: COLOR.yield },
  { key: "dollar_part", label: "Dollar", color: COLOR.dollar },
  { key: "haven_part", label: "Haven", color: COLOR.haven },
  { key: "own_trailing_drift", label: "Drift", color: COLOR.drift },
  { key: "unexplained_1", label: "Unexplained", color: COLOR.u },
] as const;

export type PartKey = (typeof PARTS)[number]["key"];

/** The published label of the 63-day explained share. */
export const LABEL_TEXT: Record<string, string> = {
  much: "explain a lot",
  part: "explain some",
  little: "explain little",
};

export function fmt(v: number, digits = 2): string {
  const s = Math.abs(v).toFixed(digits);
  return v > 0 ? `+${s}` : v < 0 ? `−${s}` : s;
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

export const AXIS = { fontSize: 10, fill: "var(--text-muted)" } as const;

/** Year labels on a by-index x axis; a window starting late in a year skips that label. */
export function yearTicks(dates: string[]): { i: number; label: string }[] {
  const out: { i: number; label: string }[] = [];
  dates.forEach((d, i) => {
    const y = d.slice(0, 4);
    const first = i === 0 && d.slice(5, 7) <= "03";
    if (first || (i > 0 && dates[i - 1].slice(0, 4) !== y))
      out.push({ i, label: y });
  });
  return out;
}
