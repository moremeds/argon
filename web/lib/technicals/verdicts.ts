// The Technicals surface's small verdict engines — the plain-English reads and
// badge labels derived from detail fields. Pure string/enum logic shared by the
// React panels and the Node MCP tools; components keep the color mapping and
// markup.
import { fmtDecimal } from "@/lib/formatters";

// Plain-English take on the three MA slopes: how many are statistically
// reliable (|t| >= 2) and whether they point the same way. Complements the
// ALIGN badge (which reports stack order, not velocity).
export function kinematicsReading(
  t20: number | null | undefined,
  t50: number | null | undefined,
  t200: number | null | undefined,
): string | null {
  const known = [t20, t50, t200].filter(
    (t): t is number => typeof t === "number",
  );
  if (known.length < 3) return null;
  const sig = known.filter((t) => Math.abs(t) >= 2);
  if (sig.length === 0)
    return "Reading: no MA slope is statistically reliable — no trend.";
  const up = sig.filter((t) => t > 0).length;
  const down = sig.filter((t) => t < 0).length;
  if (up > 0 && down > 0)
    return `Reading: slopes disagree (${sig.length}/3 reliable) — no clean trend.`;
  const conf = sig.length === 3 ? "all three MAs" : `${sig.length}/3 MAs`;
  const dir = up > 0 ? "rising" : "falling";
  const strength = sig.length === 3 ? "confirmed" : "tentative";
  const verdict = up > 0 ? "uptrend" : "downtrend";
  return `Reading: ${conf} ${dir}, statistically reliable — ${strength} ${verdict}.`;
}

export type AlignmentBadge = {
  /** BULL for a > 0, BEAR for a < 0, MIXED for a == 0 — the component colors
   *  off this label. */
  label: "BULL" | "BEAR" | "MIXED";
  /** |a| — how many of the 3 MAs are stacked that way. */
  count: number;
  /** e.g. "BULL ALIGN 2/3" — the rendered badge text. */
  text: string;
};

// Alignment badge: the direction (BULL/BEAR/MIXED) and how many of the 3 MAs
// are stacked that way (|a|/3).
export function alignmentBadge(
  a: number | null | undefined,
): AlignmentBadge | null {
  if (a == null) return null;
  const label = a > 0 ? "BULL" : a < 0 ? "BEAR" : "MIXED";
  const count = Math.abs(a);
  return { label, count, text: `${label} ALIGN ${count}/3` };
}

// The dual-MACD detail block, as carried on TechnicalsResponse.detail.
export type DualMacdDetail = {
  trend_state?: string;
  tactical_signal?: string;
  confidence?: number | null;
};

// The dual-MACD badge's text plus the raw signal key the chart's color mapping
// classifies (tactical signal when present and not "NONE", else the trend
// state). Backend trend_state ∈ {BULLISH, BEARISH, DETERIORATING, IMPROVING}
// (cards/technicals.py dual_macd_state).
export function macdSignalText(
  dm: DualMacdDetail | undefined,
): { text: string; key: string } | null {
  if (!dm) return null;
  const hasTactical = !!dm.tactical_signal && dm.tactical_signal !== "NONE";
  const text = hasTactical
    ? `${dm.tactical_signal} · conf ${fmtDecimal(dm.confidence, 2)}`
    : dm.trend_state;
  if (!text) return null;
  return {
    text,
    key: hasTactical ? dm.tactical_signal! : dm.trend_state!,
  };
}

/** Why the sigmoid fit was rejected, in plain English. Derived from the two R²
 * values the payload already carries + the backend's validity gate
 * (r2_sig ≥ 0.80 AND r2_sig ≥ r2_lin + 0.05 AND k > 0). The old copy hardcoded
 * only the beats-linear clause, so on an absolute-fit miss it printed the false
 * "0.31 ≤ 0.05 + 0.05" — this names the clause that actually failed.
 * ponytail: the 0.80 mirrors fit_sigmoid()'s gate — copy-only; drift here just
 * softens wording, never a data bug. */
export function sigmoidRejectReason(
  r2Sig: number | null | undefined,
  r2Lin: number | null | undefined,
): string {
  const pct = (x: number) => `${Math.round(x * 100)}%`;
  if (r2Sig == null)
    return "not enough clean history since the last pivot to fit a curve";
  if (r2Sig < 0.8)
    return `the move is too choppy for a clean S-curve — the fit explains only ${pct(r2Sig)} of it (an S-curve needs ≥ 80%)`;
  // Without r2_linear we can't tell the beats-linear clause from the k clause —
  // so don't assert either; stay generic rather than blame the wrong one.
  if (r2Lin == null)
    return "the S-curve doesn't clear the bar over a plain trend line";
  if (r2Sig < r2Lin + 0.05)
    return `a straight line already explains it about as well (S-curve ${pct(r2Sig)} vs linear ${pct(r2Lin)}) — the trend is roughly linear, not an S`;
  return "the fitted curve bends the wrong way (decelerating into the pivot)";
}
