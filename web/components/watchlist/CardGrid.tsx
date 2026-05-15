"use client";
import type { components } from "@/lib/types";
import { TickerCard } from "./TickerCard";

type WatchlistCard = components["schemas"]["WatchlistCard"];
type WatchlistResponse = components["schemas"]["WatchlistResponse"];

const PRIORITY_SECTORS = ["ETF", "M7", "Semiconductor"] as const;

function sectorRank(sector: string, tickers: WatchlistCard[]) {
  const priority = PRIORITY_SECTORS.indexOf(
    sector as (typeof PRIORITY_SECTORS)[number],
  );
  if (priority >= 0) return priority;
  return (
    PRIORITY_SECTORS.length +
    Math.min(...tickers.map((t) => t.sort_rank), Number.MAX_SAFE_INTEGER)
  );
}

function sizeValue(card: WatchlistCard) {
  const raw =
    card.sector === "ETF"
      ? (card.aum ?? card.market_cap)
      : (card.market_cap ?? card.aum);
  if (raw == null) return null;
  const value = Number(raw);
  return Number.isFinite(value) ? value : null;
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
