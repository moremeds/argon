"use client";
import type { components } from "@/lib/types";
import { TickerCard } from "./TickerCard";

type WatchlistCard = components["schemas"]["WatchlistCard"];
type WatchlistResponse = components["schemas"]["WatchlistResponse"];

export function CardGrid({ data }: { data: WatchlistResponse }) {
  const grouped = new Map<string, WatchlistCard[]>();
  for (const t of data.tickers) {
    const arr = grouped.get(t.sector) ?? [];
    arr.push(t);
    grouped.set(t.sector, arr);
  }
  for (const arr of grouped.values()) {
    arr.sort((a, b) => Number(b.pinned) - Number(a.pinned));
  }

  return (
    <div>
      {[...grouped.entries()].map(([sector, tickers]) => (
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
              <TickerCard key={t.ticker} card={t} />
            ))}
          </div>
        </section>
      ))}
    </div>
  );
}
