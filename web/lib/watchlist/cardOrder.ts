// Watchlist card ordering, verbatim from components/watchlist/CardGrid.tsx:
// pinned-first then size-then-sort_rank within a sector; priority sectors
// first, then remaining sectors ranked by their largest member's size.
// PRIORITY_SECTORS is imported, not copied — the taxonomy owns the constants.
import type { components } from "@/lib/types";
import { toNum } from "@/lib/formatters";
import { PRIORITY_SECTORS } from "@/components/watchlist/sectorGroups";

export type WatchlistCard = components["schemas"]["WatchlistCard"];

export function sectorRank(sector: string, tickers: WatchlistCard[]) {
  const priority = PRIORITY_SECTORS.indexOf(
    sector as (typeof PRIORITY_SECTORS)[number],
  );
  if (priority >= 0) return priority;

  // Non-priority sectors: rank by max size of their members, so the sector
  // that floats up is the one whose top card on display is biggest. Aligns
  // sector ordering with `compareCards`'s within-section size ordering.
  const maxSize = tickers.reduce<number>(
    (m, t) => Math.max(m, sizeValue(t) ?? -Infinity),
    -Infinity,
  );
  if (maxSize === -Infinity) {
    // All members unpriced — push past priced sectors but keep server-curated
    // sort_rank as a stable fallback so unpriced sectors keep a deterministic
    // relative order.
    return (
      PRIORITY_SECTORS.length +
      Number.MAX_SAFE_INTEGER / 2 +
      tickers.reduce<number>(
        (m, t) => Math.min(m, t.sort_rank),
        Number.MAX_SAFE_INTEGER,
      )
    );
  }
  // Subtract from a large constant so larger maxSize ⇒ smaller rank ⇒ earlier.
  return PRIORITY_SECTORS.length + (Number.MAX_SAFE_INTEGER / 2 - maxSize);
}

const ETF_LIKE_SECTORS = new Set(["Beta", "Sector-ETF", "Credit", "Macro"]);

export function sizeValue(card: WatchlistCard) {
  const raw = ETF_LIKE_SECTORS.has(card.sector)
    ? (card.aum ?? card.market_cap)
    : (card.market_cap ?? card.aum);
  return toNum(raw);
}

export function compareCards(a: WatchlistCard, b: WatchlistCard) {
  const pinDiff = Number(b.pinned) - Number(a.pinned);
  if (pinDiff !== 0) return pinDiff;

  const aSize = sizeValue(a);
  const bSize = sizeValue(b);
  if (aSize !== null && bSize !== null && aSize !== bSize) {
    return bSize - aSize;
  }
  if (aSize !== null) return -1;
  if (bSize !== null) return 1;

  return a.sort_rank - b.sort_rank || a.ticker.localeCompare(b.ticker);
}

/**
 * The grid's group-and-sort block, verbatim: group by sector, compareCards
 * within each group, sectorRank across groups. Returns the section pairs in
 * render order.
 */
export function groupCards(
  cards: WatchlistCard[],
): [string, WatchlistCard[]][] {
  const grouped = new Map<string, WatchlistCard[]>();
  for (const t of cards) {
    const arr = grouped.get(t.sector) ?? [];
    arr.push(t);
    grouped.set(t.sector, arr);
  }
  for (const arr of grouped.values()) {
    arr.sort(compareCards);
  }
  return [...grouped.entries()].sort(
    ([sectorA, tickersA], [sectorB, tickersB]) =>
      sectorRank(sectorA, tickersA) - sectorRank(sectorB, tickersB) ||
      sectorA.localeCompare(sectorB),
  );
}

/** Flat render order with each card's sector-group key — for the MCP tool. */
export function orderCards(
  cards: WatchlistCard[],
): { card: WatchlistCard; group: string }[] {
  return groupCards(cards).flatMap(([group, arr]) =>
    arr.map((card) => ({ card, group })),
  );
}
