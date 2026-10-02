import { Flame } from "lucide-react";
import type { components } from "@/lib/types";
import { groupCards } from "@/lib/watchlist/cardOrder";
import { TickerCard } from "./TickerCard";
import { LiveSpotsProvider } from "./LiveSpotsProvider";

type WatchlistResponse = components["schemas"]["WatchlistResponse"];

export function CardGrid({ data }: { data: WatchlistResponse }) {
  const groupedEntries = groupCards(data.tickers);

  const hotCount = data.hot_count ?? 0;
  const hotMax = data.hot_max ?? 0;
  const hotOver = hotMax > 0 && hotCount > hotMax;

  return (
    // One grid-wide poller: every TickerCard reads its live spot from this
    // provider's context instead of each card polling on its own.
    <LiveSpotsProvider>
      {hotMax > 0 && (
        <div
          title={
            hotOver
              ? "More hot tickers than the budget fast-lane covers — overflow waits for UW budget"
              : "Hot tickers on the fast-lane intraday refresh"
          }
          style={{
            fontFamily: "var(--font-mono)",
            fontSize: 11,
            letterSpacing: 1.5,
            textTransform: "uppercase",
            color: hotOver ? "var(--warning)" : "var(--text-muted)",
            marginBottom: 16,
            display: "inline-flex",
            alignItems: "center",
            gap: 6,
          }}
        >
          <Flame size={12} fill="currentColor" />
          Hot {hotCount} / {hotMax}
          {hotOver ? " · overflow queued" : ""}
        </div>
      )}
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
              <TickerCard key={t.ticker} card={t} />
            ))}
          </div>
        </section>
      ))}
    </LiveSpotsProvider>
  );
}
