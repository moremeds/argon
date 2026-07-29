import type { components } from "@/lib/types";

// Shared by the Flow and Discover sub-tabs, which section their cards the same
// way. Extracted when Discover became its own tab rather than duplicated —
// two copies drift the moment a bias is renamed.
type Candidate = components["schemas"]["ScannerCandidate"];
export type Bias = Candidate["bias"];

export const SECTION_ORDER: Bias[] = ["bullish", "bearish", "mixed", "neutral"];

export const SECTION_TITLE: Record<Bias, string> = {
  bullish: "BULLISH",
  bearish: "BEARISH",
  mixed: "MIXED",
  neutral: "NO DIRECTIONAL READ",
};

export const SECTION_COLOR: Record<Bias, string> = {
  bullish: "var(--positive)",
  bearish: "var(--negative)",
  mixed: "var(--warning)",
  neutral: "var(--text-muted)",
};
