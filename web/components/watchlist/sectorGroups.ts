export type SectorCluster = "core" | "ai" | "other";

export type SectorGroup = {
  /** Stable id for rail state. Not persisted — the URL still carries `sector`. */
  key: string;
  /** Rail text. Uppercased at render. */
  label: string;
  /** Full layer name. Shown as the chain-row caption, and as the rail tooltip. */
  full: string;
  cluster: SectorCluster;
  /** Chain tags. These are the values that reach `?sector=`. */
  items: string[];
  /**
   * Rail click filters straight to `items[0]` instead of opening a chain row.
   * For groups whose name IS the tag (M7), a chain row holding one chip that
   * repeats the group name is pure noise.
   */
  leaf?: boolean;
};

/**
 * Rail order is deliberate: Index/Macro and M7 lead because that is the
 * top-of-session read — what beta is doing, what the megacaps are doing —
 * before drilling into any chain. The five AI layers stay contiguous so
 * they read as one cluster rather than five unrelated groups.
 *
 * `items` lists tags that exist in `uw_scan.watchlist.sector` TODAY. The
 * Model & Tooling layer and the wider chain set from
 * docs/research/2026-08-09-watchlist-industry-chains/ arrive with the chain
 * migration; a rail button that filters to an empty grid is worse than one
 * that isn't there yet, so layers land here as their tags land in the DB.
 */
export const SECTOR_GROUPS: SectorGroup[] = [
  {
    key: "index",
    label: "Index",
    full: "Index & Macro",
    cluster: "core",
    items: ["Beta", "Sector-ETF", "Credit", "Macro"],
  },
  {
    key: "m7",
    label: "M7",
    full: "Cross-cutting",
    cluster: "core",
    items: ["M7"],
    leaf: true,
  },
  {
    key: "chip",
    label: "Chip",
    full: "Chip & System",
    cluster: "ai",
    items: ["Foundry", "Semi-Logic", "Semi-Cap", "Memory"],
  },
  {
    key: "cloud",
    label: "Cloud",
    full: "Cloud & Data Platform",
    cluster: "ai",
    items: ["NeoCloud"],
  },
  {
    key: "dc",
    label: "DC",
    full: "Datacenter Infrastructure",
    cluster: "ai",
    items: ["DC-Connect", "Power"],
  },
  {
    key: "app",
    label: "App",
    full: "Application & Endpoint",
    cluster: "ai",
    items: ["SaaS"],
  },
  {
    key: "thematic",
    label: "Thematic",
    full: "Thematic",
    cluster: "other",
    items: ["Crypto", "Fintech", "Space"],
  },
  {
    key: "defensive",
    label: "Defensive",
    full: "Defensive",
    cluster: "other",
    items: ["Healthcare", "Energy", "Banks", "Consumer"],
  },
];

/** The group whose chain row should be open for a given `?sector=` value. */
export function groupForSector(
  sector: string | undefined,
): SectorGroup | undefined {
  if (!sector || sector === "All") return undefined;
  return SECTOR_GROUPS.find((g) => g.items.includes(sector));
}

/** Grouped label/items pairs — consumed by AddTickerDialog's sector picker. */
export const SECTOR_ROWS: { label: string; items: string[] }[] =
  SECTOR_GROUPS.map((g) => ({ label: g.label, items: g.items }));

export const WATCHLIST_SECTORS = SECTOR_GROUPS.flatMap((g) => g.items);

export const PRIORITY_SECTORS = ["Beta", "M7", "Semi-Logic"] as const;
