import type { WatchlistChainInfo } from "@/lib/api";

export type SectorCluster = "core" | "ai" | "other";

export type SectorGroup = {
  /** Stable id for rail state. Not persisted — the URL carries `chain`. */
  key: string;
  /** Rail text. Uppercased at render. */
  label: string;
  /** Full layer name. Shown as the chain-row caption and the rail tooltip. */
  full: string;
  cluster: SectorCluster;
  /** Chain names. These are the values that reach `?chain=`. */
  items: string[];
  /**
   * Rail click filters straight to `items[0]` instead of opening a chain row.
   * For a layer whose name IS its only chain (M7), a chain row holding one chip
   * that repeats the group name is pure noise.
   */
  leaf?: boolean;
};

/**
 * Rail order, and which layers lead. Index & Macro and M7 come first because
 * that is the top-of-session read — what beta is doing, what the megacaps are
 * doing — before drilling into a chain.
 *
 * Everything else is DERIVED from `/api/watchlist/chains`, not hardcoded. The
 * taxonomy lives in `uw_scan.watchlist_taxonomy`; duplicating 38 chain names
 * here would reintroduce exactly the drift that module exists to prevent.
 */
const LAYER_ORDER = ["IDX", "X", "L1", "L2", "L3", "L4", "L5", "THM", "DEF"];

const LAYER_LABEL: Record<string, string> = {
  IDX: "Index",
  X: "M7",
  L1: "Chip",
  L2: "Cloud",
  L3: "DC",
  L4: "App",
  L5: "Model",
  THM: "Thematic",
  DEF: "Defensive",
};

const LAYER_CLUSTER: Record<string, SectorCluster> = {
  IDX: "core",
  X: "core",
  L1: "ai",
  L2: "ai",
  L3: "ai",
  L4: "ai",
  L5: "ai",
  THM: "other",
  DEF: "other",
};

/**
 * Build the rail from live chain rows.
 *
 * Chains with zero members are dropped: a rail button that filters to an empty
 * grid is worse than one that isn't there. That is what previously forced the
 * Model & Tooling layer out of the UI entirely — its members existed but were
 * unreachable under a single-tag schema, so the layer looked empty.
 */
export function buildSectorGroups(chains: WatchlistChainInfo[]): SectorGroup[] {
  const byLayer = new Map<string, WatchlistChainInfo[]>();
  for (const c of chains) {
    if (c.count <= 0) continue;
    const arr = byLayer.get(c.layer) ?? [];
    arr.push(c);
    byLayer.set(c.layer, arr);
  }

  const groups: SectorGroup[] = [];
  for (const layer of LAYER_ORDER) {
    const rows = byLayer.get(layer);
    if (!rows || rows.length === 0) continue;
    groups.push({
      key: layer.toLowerCase(),
      label: LAYER_LABEL[layer] ?? layer,
      full: rows[0].layer_name,
      cluster: LAYER_CLUSTER[layer] ?? "other",
      items: rows.map((r) => r.chain),
      leaf: rows.length === 1 && rows[0].chain === LAYER_LABEL[layer],
    });
  }
  // Any layer the server knows about that we have no order entry for still
  // renders, rather than silently vanishing when the taxonomy grows.
  for (const [layer, rows] of byLayer) {
    if (LAYER_ORDER.includes(layer)) continue;
    groups.push({
      key: layer.toLowerCase(),
      label: rows[0].layer_name,
      full: rows[0].layer_name,
      cluster: "other",
      items: rows.map((r) => r.chain),
    });
  }
  return groups;
}

/** The group whose chain row should be open for a given `?chain=` value. */
export function groupForChain(
  groups: SectorGroup[],
  chain: string | undefined,
): SectorGroup | undefined {
  if (!chain || chain === "All") return undefined;
  return groups.find((g) => g.items.includes(chain));
}

/** Member counts keyed by chain, for the rail's count badges. */
export function chainCounts(
  chains: WatchlistChainInfo[],
): Record<string, number> {
  return Object.fromEntries(chains.map((c) => [c.chain, c.count]));
}

/**
 * Legacy sector list for the Add Ticker dialog, which still writes the single
 * `watchlist.sector` column. Grouped by layer name so the picker keeps its
 * headings.
 */
export function sectorRowsFromChains(
  chains: WatchlistChainInfo[],
): { label: string; items: string[] }[] {
  const out = new Map<string, string[]>();
  for (const c of chains) {
    const arr = out.get(c.layer_name) ?? [];
    arr.push(c.chain);
    out.set(c.layer_name, arr);
  }
  return [...out.entries()].map(([label, items]) => ({ label, items }));
}

export const PRIORITY_SECTORS = ["Beta", "M7", "Semi-Logic"] as const;
