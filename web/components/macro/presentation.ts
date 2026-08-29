export type PresentationBasis = "REAL" | "COMPUTED" | "PLANNED" | "REFERENCE";

const EXACT_LABELS: Readonly<Record<string, string>> = {
  WELL_ABOVE_TARGET: "Well above target",
  WELL_BELOW_TARGET: "Well below target",
  ON_HOLD: "On hold",
  IN_RANGE: "In range",
  RANGEBOUND: "Range-bound",
  SUPPLY_TIGHT: "Tight supply",
  DESCRIPTIVE_ONLY: "Descriptive only",
  L1: "Structural",
  L2: "Cyclical",
  L3: "Valuation",
  frenzy_capital: "Frenzy Capital",
  fomc_statement: "FOMC statement",
  fed_sep: "Fed projections",
  nyfed_sme: "New York Fed dealer survey",
  new_york_fed_sme: "New York Fed dealer survey",
  federal_reserve_sep: "Fed projections",
  federal_reserve_fomc: "FOMC",
  policy_rates: "Policy & Rates",
  cpi_pce_divergence: "CPI–PCE divergence",
  breadth_contradicts_core: "Breadth conflicts with core",
  percent_annual_rate: "Annual rate",
  corr_60d: "60-day correlation",
  MICH: "Michigan survey",
  T5YIFR: "5Y5Y inflation forward",
  RTWEXBGS: "Real broad dollar",
  cb_gold_reserves_monthly: "Central-bank gold reserves",
  lbma_inventory_daily: "LBMA inventory",
  exchange_inventory_daily: "Exchange inventory",
  spx_series: "S&P 500",
  fx_rows: "Gold FX basket",
  compute_structural_posture: "Structural model",
  compute_valuation_overlay: "Valuation model",
  asset_mgr_net_pct_oi_change_4w:
    "Asset managers · 4-week net share change",
  dealer_net_pct_oi_change_4w: "Dealers · 4-week net share change",
  lev_money_net_pct_oi_change_4w:
    "Leveraged funds · 4-week net share change",
  sofr_effr_spread_change_4w: "SOFR–EFFR spread · 4-week change",
  sofr_effr_spread_change_13w: "SOFR–EFFR spread · 13-week change",
};

const FIELD_LABELS: Readonly<Record<string, string>> = {
  confidence_reasons: "Confidence drivers",
  series_id: "Series",
  available_at: "Available",
  as_of: "As of",
  computed_at: "Computed",
  change_over_window: "Change",
  causal_role: "Role",
  probability_distribution: "Meeting odds",
  market_implied: "Market path",
};

const SERIES_LABELS: Readonly<Record<string, string>> = {
  DGS10: "10Y Treasury",
  DFII10: "10Y real yield",
  T10YIE: "10Y breakeven",
  DTWEXBGS: "Broad dollar",
  DGS2: "2Y Treasury",
  DGS5: "5Y Treasury",
  DGS30: "30Y Treasury",
  DFF: "Effective fed funds",
  SOFR: "SOFR",
};

const ACRONYMS = new Set([
  "cb",
  "comex",
  "cot",
  "cpi",
  "effr",
  "etf",
  "fed",
  "fomc",
  "fx",
  "gld",
  "lbma",
  "oi",
  "pce",
  "sep",
  "sofr",
  "tff",
  "usd",
]);

function sentenceWord(word: string, index: number): string {
  const lower = word.toLowerCase();
  if (ACRONYMS.has(lower)) return lower.toUpperCase();
  if (/^\d+[dwmy]$/.test(lower)) return lower.replace(/[dwmy]$/, (unit) => unit.toUpperCase());
  if (index === 0) return lower.charAt(0).toUpperCase() + lower.slice(1);
  return lower;
}

/** Presentation boundary for enum values and field-shaped labels. */
export function humanizeIdentifier(value: string): string {
  const exact = EXACT_LABELS[value];
  if (exact) return exact;
  return value
    .replaceAll("-", " ")
    .split("_")
    .filter(Boolean)
    .map(sentenceWord)
    .join(" ");
}

/** Humanize variable-shaped tokens embedded in publisher prose without rewriting it. */
export function humanizeText(value: string): string {
  return value.replace(
    /\b[A-Za-z][A-Za-z0-9]*_[A-Za-z0-9_]+\b/g,
    (identifier) => humanizeIdentifier(identifier),
  );
}

export function fieldLabel(value: string): string {
  return FIELD_LABELS[value] ?? humanizeIdentifier(value);
}

export function seriesLabel(value: string): string {
  return SERIES_LABELS[value] ?? humanizeIdentifier(value);
}

export function basisLabel(value: PresentationBasis): string {
  if (value === "REAL") return "Live";
  if (value === "COMPUTED") return "Derived";
  if (value === "REFERENCE") return "Reference";
  return "Planned";
}
