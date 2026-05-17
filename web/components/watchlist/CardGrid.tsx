import type { components } from "@/lib/types";
import { toNum } from "@/lib/formatters";
import { PRIORITY_SECTORS } from "./sectorGroups";
import { TickerCard } from "./TickerCard";

type WatchlistCard = components["schemas"]["WatchlistCard"];
type WatchlistResponse = components["schemas"]["WatchlistResponse"];

function sectorRank(sector: string, tickers: WatchlistCard[]) {
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

function sizeValue(card: WatchlistCard) {
  const raw =
    card.sector === "ETF"
      ? (card.aum ?? card.market_cap)
      : (card.market_cap ?? card.aum);
  return toNum(raw);
}

function compareCards(a: WatchlistCard, b: WatchlistCard) {
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

export function CardGrid({
  data,
  sparklines,
}: {
  data: WatchlistResponse;
  sparklines: Record<string, number[]>;
}) {
  const grouped = new Map<string, WatchlistCard[]>();
  for (const t of data.tickers) {
    const arr = grouped.get(t.sector) ?? [];
    arr.push(t);
    grouped.set(t.sector, arr);
  }
  for (const arr of grouped.values()) {
    arr.sort(compareCards);
  }
  const groupedEntries = [...grouped.entries()].sort(
    ([sectorA, tickersA], [sectorB, tickersB]) =>
      sectorRank(sectorA, tickersA) - sectorRank(sectorB, tickersB) ||
      sectorA.localeCompare(sectorB),
  );

  return (
    <div>
      {groupedEntries.map(([sector, tickers]) => (
        <section key={sector} style={{ marginBottom: 28 }}>
          <h2
            style={{
              fontFamily: "var(--font-mono)",
              fontSize: 11,
              letterSpacing: 1.5,
              color: "var(--text-secondary)",
              textTransform: "uppercase",
              marginBottom: 8,
              paddingBottom: 4,
              borderBottom: "1px solid var(--border-dim)",
            }}
          >
            {sector} · {tickers.length}
          </h2>
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(auto-fill, minmax(280px, 1fr))",
              gap: 12,
            }}
          >
            {tickers.map((t) => (
              <TickerCard
                key={t.ticker}
                card={t}
                sparkline={sparklines[t.ticker] ?? []}
              />
            ))}
          </div>
        </section>
      ))}
    </div>
  );
}
