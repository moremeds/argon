/**
 * Shared vocabulary for the AI/semi chain desk: palette, labels, formatting.
 *
 * The palette is read from argon's CSS custom properties at paint time rather
 * than hard-coded, so a canvas follows the theme toggle the same way the DOM
 * does — `readPalette()` is called again on a theme change and the scenes
 * redraw. Hard-coding a hex here would give the light theme dark-theme charts.
 */

import type { CaseStage, ChainMetricCell } from "@/lib/api";

export const DASH = "—";
export const TIMES = "×";
export const MID = "·";
export const RARR = "→";
export const LARR = "←";

export const LAYER_KEYS = ["L1", "L2", "L3", "L4", "L5"] as const;

/** The taxonomy's five layers, spelled for a reader. */
export const LAYER_LABELS: Record<string, string> = {
  L1: "Silicon & equipment",
  L2: "Cloud & platform",
  L3: "Physical buildout",
  L4: "Applications & devices",
  L5: "Software & services",
};

/**
 * Stage layer -> display label.
 *
 * Editorial, and therefore HERE rather than in the API contract: a label map
 * is a rendering choice, and a stored report replaying an old label would be
 * reproducing a caption rather than an answer. A layer with no entry falls
 * back to its own key, so a taxonomy row added tomorrow renders as itself
 * instead of vanishing.
 */
export const STAGE_LABELS: Record<string, string> = {
  "Upstream-Components": "Upstream components",
  "Semi-DSP-Switch": "Switch silicon / DSP",
  "Module-Transceiver": "Modules & transceivers",
  "Systems-Networking": "Systems & networking",
  "Customer-Cloud": "Customer — cloud",
  "EPC-Construction": "EPC & construction",
  Generation: "Generation & fuel",
  "Power-Electrical": "Power & electrical",
  "Cooling-Thermal": "Cooling & thermal",
  "DC-REIT-Colo": "Customer — colo / REIT",
};

export function stageLabel(layer: string): string {
  return STAGE_LABELS[layer] ?? layer;
}

export interface DeskPalette {
  ink: string;
  body: string;
  mute: string;
  faint: string;
  rule: string;
  card: string;
  grid: string;
  good: string;
  bad: string;
  warn: string;
  /** One colour per taxonomy layer, L1..L5. */
  layer: string[];
}

const TOKENS: Record<keyof Omit<DeskPalette, "layer">, string> = {
  ink: "--text-primary",
  body: "--text-secondary",
  mute: "--text-secondary",
  faint: "--text-muted",
  rule: "--border-dim",
  card: "--bg-panel",
  grid: "--chart-grid",
  good: "--positive",
  bad: "--negative",
  warn: "--warning",
};

/**
 * L1..L5. Five hues that stay distinguishable in both themes.
 *
 * EXPORTED because the legend swatches are DOM and the nodes are canvas: two
 * copies of this list drift, and when they do the legend's dot stops matching
 * the sphere it names — which is the one thing tying the two halves of the map
 * together.
 */
export const LAYER_TOKENS = [
  "--signal-strong",
  "--accent-cool",
  "--extreme",
  "--warning",
  "--dislocation",
];

export function readPalette(): DeskPalette {
  const style = getComputedStyle(document.documentElement);
  const read = (name: string) => style.getPropertyValue(name).trim();
  return {
    ink: read(TOKENS.ink),
    body: read(TOKENS.body),
    mute: read(TOKENS.mute),
    faint: read(TOKENS.faint),
    rule: read(TOKENS.rule),
    card: read(TOKENS.card),
    grid: read(TOKENS.grid),
    good: read(TOKENS.good),
    bad: read(TOKENS.bad),
    warn: read(TOKENS.warn),
    layer: LAYER_TOKENS.map(read),
  };
}

/**
 * Subscribe to every way argon's theme can change, and to font load.
 *
 * Three sources, not one: the explicit toggle stamps `data-theme` on <html>,
 * an un-stamped document follows `prefers-color-scheme`, and a canvas painted
 * before IBM Plex Mono arrives measures the fallback face and lays its labels
 * out for the wrong metrics. Returns its own unsubscribe.
 */
export function onThemeChange(repaint: () => void): () => void {
  const media = window.matchMedia("(prefers-color-scheme: dark)");
  media.addEventListener("change", repaint);
  const observer = new MutationObserver(repaint);
  observer.observe(document.documentElement, {
    attributes: true,
    attributeFilter: ["data-theme"],
  });
  document.fonts?.ready.then(repaint).catch(() => {
    // A font that never resolves leaves the first paint standing, which is
    // correct output in a fallback face — not a reason to surface an error.
  });
  return () => {
    media.removeEventListener("change", repaint);
    observer.disconnect();
  };
}

/** `#rgb` / `#rrggbb` -> `rgba(...)`. Non-hex input is returned unchanged, so
 *  a token that already holds an `rgba()` (argon's `--chart-grid`) survives. */
export function alpha(color: string, a: number): string {
  const hex = color.trim().replace("#", "");
  if (!/^([0-9a-f]{3}|[0-9a-f]{6})$/i.test(hex)) return color;
  const full =
    hex.length === 3
      ? hex[0] + hex[0] + hex[1] + hex[1] + hex[2] + hex[2]
      : hex;
  const n = parseInt(full, 16);
  return `rgba(${(n >> 16) & 255},${(n >> 8) & 255},${n & 255},${a})`;
}

/** A share, as a percentage. `na` for null — never `0%`, which is an answer. */
export function pct(v: number | null | undefined, digits = 1): string {
  return v == null ? "na" : `${(v * 100).toFixed(digits)}%`;
}

/** A change, signed. `na` for null. */
export function sgn(v: number | null | undefined, digits = 1): string {
  if (v == null) return "na";
  return `${v >= 0 ? "+" : ""}${(v * 100).toFixed(digits)}%`;
}

/** Dollars, in billions. Only ever applied to the USD-filer capex panel. */
export function usdB(v: number, digits = 1): string {
  return `$${(v / 1e9).toFixed(digits)}B`;
}

export function median(values: number[]): number | null {
  if (values.length === 0) return null;
  const s = [...values].sort((a, b) => a - b);
  const n = s.length;
  return n % 2 ? s[(n - 1) / 2] : (s[n / 2 - 1] + s[n / 2]) / 2;
}

/** Pearson r and its t statistic, or null when n < 3 or either side is flat. */
export function correlation(
  pairs: [number, number][],
): { r: number; t: number; n: number } | null {
  const n = pairs.length;
  if (n < 3) return null;
  const mx = pairs.reduce((a, p) => a + p[0], 0) / n;
  const my = pairs.reduce((a, p) => a + p[1], 0) / n;
  const cov = pairs.reduce((a, p) => a + (p[0] - mx) * (p[1] - my), 0) / n;
  const sx = Math.sqrt(pairs.reduce((a, p) => a + (p[0] - mx) ** 2, 0) / n);
  const sy = Math.sqrt(pairs.reduce((a, p) => a + (p[1] - my) ** 2, 0) / n);
  if (sx === 0 || sy === 0) return null;
  const r = cov / (sx * sy);
  if (Math.abs(r) >= 1) return { r, t: Infinity, n };
  return { r, t: (r * Math.sqrt(n - 2)) / Math.sqrt(1 - r * r), n };
}

/** One chain, reshaped from the matrix for placement on the map. */
export interface ChainPoint {
  chain: string;
  layer: string;
  layerIndex: number;
  members: number;
  revYoy: number | null;
  grossMargin: number | null;
  /** Members carrying a `rev_yoy` — printed beside every median. */
  reporting: number;
}

/**
 * Chains that sit on a taxonomy PLANE, reshaped for the chain map.
 *
 * `layer_rank !== 0` is dropped on purpose and is not a gap: a positive rank
 * means the chain is a ranked stage of a modelled flow, which the case funnels
 * draw. A chain with no median on either axis is also dropped — it has no
 * position, and placing it at the origin would put "we hold nothing for this"
 * at "average growth, average margin".
 */
export function chainPoints(cells: ChainMetricCell[]): ChainPoint[] {
  const byChain = new Map<string, ChainPoint>();
  for (const cell of cells) {
    if (cell.layer_rank !== 0) continue;
    const layerIndex = LAYER_KEYS.indexOf(
      cell.layer as (typeof LAYER_KEYS)[number],
    );
    if (layerIndex < 0) continue;
    const point = byChain.get(cell.chain) ?? {
      chain: cell.chain,
      layer: cell.layer,
      layerIndex,
      members: cell.members_total,
      revYoy: null,
      grossMargin: null,
      reporting: 0,
    };
    if (cell.metric === "rev_yoy") {
      point.revYoy = cell.median;
      point.reporting = cell.dots.filter((d) => d.value !== null).length;
    }
    if (cell.metric === "gross_margin") point.grossMargin = cell.median;
    byChain.set(cell.chain, point);
  }
  return [...byChain.values()].filter(
    (p) => p.revYoy !== null && p.grossMargin !== null,
  );
}

/** One name's own-history percentile, deduped across the chains it sits in. */
export interface ValuationMark {
  ticker: string;
  percentile: number;
}

export function valuationMarks(cells: ChainMetricCell[]): {
  marks: ValuationMark[];
  universe: number;
} {
  const seen = new Map<string, number | null>();
  for (const cell of cells) {
    if (cell.metric !== "valuation_percentile") continue;
    // Membership is (chain, layer, ticker)-grained, so a name in two chains
    // arrives twice and must be counted once — otherwise the "N of M"
    // headline can print a numerator larger than its own denominator.
    for (const dot of cell.dots) {
      if (!seen.has(dot.ticker)) seen.set(dot.ticker, dot.value);
    }
  }
  const marks: ValuationMark[] = [];
  for (const [ticker, value] of seen) {
    if (value !== null) marks.push({ ticker, percentile: value });
  }
  marks.sort((a, b) => a.percentile - b.percentile);
  return { marks, universe: seen.size };
}

/** A case, summarised for the cards and the funnel headers. */
/**
 * One accent per case, in the order the API returns them.
 *
 * Also exported for one reason: the case CARD, the funnel HEADER and the stage
 * TABLE heading are three separate components showing the same case, and the
 * colour is what says so. Three private copies is three chances for the
 * datacenter card to be purple while its funnel is amber.
 */
export const CASE_TOKENS = ["--extreme", "--warning"];

export function caseToken(index: number): string {
  return CASE_TOKENS[index % CASE_TOKENS.length];
}

/**
 * Growth beyond this is clamped to the funnel's rim.
 *
 * A CONSTANT, not a fitted maximum: a cap taken from the data would let one
 * outlier compress every other stage, and — because both cases share one
 * radius scale — it would silently rewrite the other case's shape too.
 *
 * Shared with the stage table, which FLAGS the names that hit it. Two copies
 * would let the table flag a different set from the one the funnel actually
 * clamps, and the reader would have no way to tell.
 */
export const GROWTH_CAP = 0.8;

export interface CaseSummary {
  /** Customer first, upstream last — the funnel's drawing order. */
  downstreamFirst: CaseStage[];
  customer: CaseStage;
  upstream: CaseStage;
  /** Upstream median growth divided by the customer's. Null if either is
   *  missing or the customer's is not positive — a ratio through zero or a
   *  negative denominator is arithmetic, not amplification. */
  amplification: number | null;
  distinctCompanies: number;
  memberships: number;
  /** How many COMPANIES appear at more than one stage of the same case —
   *  a headcount, not a surplus-membership tally. */
  dualListed: number;
}

/**
 * Supplying stages growing more slowly than the customer they supply.
 *
 * SHARED, because both the case card and the funnel finding print its COUNT —
 * "N of M supplying stages sit below their own customer" — and two copies of
 * the comparison could print different N for the same case with nothing on
 * screen to say which one was right. The customer stage itself is excluded:
 * it does not supply itself, and including it would make N off by one
 * whenever a case's customers happened to be its slowest stage.
 */
export function belowCustomer(summary: CaseSummary): CaseStage[] {
  const cm = summary.customer.median_rev_yoy;
  if (cm == null) return [];
  return summary.downstreamFirst
    .slice(1)
    .filter((s) => s.median_rev_yoy != null && s.median_rev_yoy < cm);
}

export function summariseCase(stages: CaseStage[]): CaseSummary | null {
  if (stages.length < 2) return null;
  // The API orders upstream-first (rank ascending); the funnel puts the
  // customer on top so the dollar travels downward.
  const downstreamFirst = [...stages].sort((a, b) => b.rank - a.rank);
  const customer = downstreamFirst[0];
  const upstream = downstreamFirst[downstreamFirst.length - 1];
  // Per-ticker stage FREQUENCY, not a memberships-minus-distinct subtraction.
  // The card labels this number "at two stages"; a ticker appearing at three
  // stages contributes 2 to the subtraction and would be reported as two
  // companies. The count wanted is how many companies appear more than once.
  const seenAt = new Map<string, number>();
  let memberships = 0;
  for (const stage of stages) {
    memberships += stage.members.length;
    for (const m of stage.members)
      seenAt.set(m.ticker, (seenAt.get(m.ticker) ?? 0) + 1);
  }
  const tickers = seenAt;
  const repeated = [...seenAt.values()].filter((n) => n > 1).length;
  const cm = customer.median_rev_yoy;
  const um = upstream.median_rev_yoy;
  return {
    downstreamFirst,
    customer,
    upstream,
    amplification: cm != null && um != null && cm > 0 ? um / cm : null,
    distinctCompanies: tickers.size,
    memberships,
    dualListed: repeated,
  };
}
