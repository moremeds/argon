// orderCards parity with CardGrid's pre-extraction inline sort.
// Oracle = the pre-extraction component code copied verbatim (oracle_*
// names). Fixture = tests/fixtures/mcp/watchlist.json (frozen /api/watchlist
// capture, 2026-09-23). Anchors computed once from that capture.
import { describe, expect, test } from "vitest";
import type { components } from "@/lib/types";
import { toNum } from "@/lib/formatters";
import { PRIORITY_SECTORS } from "@/components/watchlist/sectorGroups";
import { groupCards, orderCards } from "@/lib/watchlist/cardOrder";
import fixture from "../../fixtures/mcp/watchlist.json";

type WatchlistCard = components["schemas"]["WatchlistCard"];
const cards = fixture.tickers as WatchlistCard[];

// ---- oracle: verbatim copy of the pre-extraction CardGrid code ----

function oracle_sectorRank(sector: string, tickers: WatchlistCard[]) {
  const priority = PRIORITY_SECTORS.indexOf(
    sector as (typeof PRIORITY_SECTORS)[number],
  );
  if (priority >= 0) return priority;

  const maxSize = tickers.reduce<number>(
    (m, t) => Math.max(m, oracle_sizeValue(t) ?? -Infinity),
    -Infinity,
  );
  if (maxSize === -Infinity) {
    return (
      PRIORITY_SECTORS.length +
      Number.MAX_SAFE_INTEGER / 2 +
      tickers.reduce<number>(
        (m, t) => Math.min(m, t.sort_rank),
        Number.MAX_SAFE_INTEGER,
      )
    );
  }
  return PRIORITY_SECTORS.length + (Number.MAX_SAFE_INTEGER / 2 - maxSize);
}

const ORACLE_ETF_LIKE = new Set(["Beta", "Sector-ETF", "Credit", "Macro"]);

function oracle_sizeValue(card: WatchlistCard) {
  const raw = ORACLE_ETF_LIKE.has(card.sector)
    ? (card.aum ?? card.market_cap)
    : (card.market_cap ?? card.aum);
  return toNum(raw);
}

function oracle_compareCards(a: WatchlistCard, b: WatchlistCard) {
  const pinDiff = Number(b.pinned) - Number(a.pinned);
  if (pinDiff !== 0) return pinDiff;

  const aSize = oracle_sizeValue(a);
  const bSize = oracle_sizeValue(b);
  if (aSize !== null && bSize !== null && aSize !== bSize) {
    return bSize - aSize;
  }
  if (aSize !== null) return -1;
  if (bSize !== null) return 1;

  return a.sort_rank - b.sort_rank || a.ticker.localeCompare(b.ticker);
}

function oracle_order(cards: WatchlistCard[]): string[] {
  const grouped = new Map<string, WatchlistCard[]>();
  for (const t of cards) {
    const arr = grouped.get(t.sector) ?? [];
    arr.push(t);
    grouped.set(t.sector, arr);
  }
  for (const arr of grouped.values()) {
    arr.sort(oracle_compareCards);
  }
  const groupedEntries = [...grouped.entries()].sort(
    ([sectorA, tickersA], [sectorB, tickersB]) =>
      oracle_sectorRank(sectorA, tickersA) -
        oracle_sectorRank(sectorB, tickersB) ||
      sectorA.localeCompare(sectorB),
  );
  return groupedEntries.flatMap(([, tickers]) => tickers.map((t) => t.ticker));
}

// ---- tests ----

describe("orderCards", () => {
  test("full order equals the pre-extraction inline sort on the fixture", () => {
    expect(orderCards(cards).map((o) => o.card.ticker)).toEqual(
      oracle_order(cards),
    );
  });

  test("anchors: first five cards and group keys", () => {
    const head = orderCards(cards)
      .slice(0, 5)
      .map((o) => `${o.group}:${o.card.ticker}`);
    expect(head).toEqual([
      "Beta:SPY",
      "Beta:QQQ",
      "Beta:IWM",
      "Beta:DIA",
      "M7:TSLA",
    ]);
  });

  test("every card appears exactly once and keeps its sector as group key", () => {
    const ordered = orderCards(cards);
    expect(ordered).toHaveLength(cards.length);
    expect(new Set(ordered.map((o) => o.card.ticker))).toEqual(
      new Set(cards.map((c) => c.ticker)),
    );
    for (const { card, group } of ordered) {
      expect(group).toBe(card.sector);
    }
  });

  test("groups are contiguous — once a sector ends it never returns", () => {
    const seen = new Set<string>();
    let prev: string | null = null;
    for (const { group } of orderCards(cards)) {
      if (group !== prev) {
        expect(seen.has(group)).toBe(false);
        seen.add(group);
        prev = group;
      }
    }
    expect(seen.size).toBe(40);
  });
});

describe("groupCards", () => {
  test("groups pair sector key with its ordered cards", () => {
    const groups = groupCards(cards);
    expect(groups.map(([s]) => s).slice(0, 3)).toEqual([
      "Beta",
      "M7",
      "Semi-Logic",
    ]);
    expect(groups[0][1].map((t) => t.ticker)).toEqual(
      cards
        .filter((c) => c.sector === "Beta")
        .sort(oracle_compareCards)
        .map((c) => c.ticker),
    );
  });
});
