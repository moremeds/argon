import { api } from "@/lib/api";
import { CardGrid } from "@/components/watchlist/CardGrid";
import { FilterBar } from "@/components/watchlist/FilterBar";
import { AddTickerDialog } from "@/components/watchlist/AddTickerDialog";
import { ScanAllButton } from "@/components/shared/ScanAllButton";

export default async function WatchlistPage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | undefined>>;
}) {
  const sp = await searchParams;
  const qs = new URLSearchParams();
  if (sp.sector) qs.set("sector", sp.sector);
  if (sp.setup) qs.set("setup", sp.setup);
  if (sp.fresh) qs.set("fresh_within_minutes", sp.fresh);
  const data = await api.watchlist(qs);

  const sparklineEntries = await Promise.all(
    data.tickers.map(async (t) => {
      try {
        const bars = await api.ohlc(t.ticker, 30);
        // /api/ohlc returns newest-first; sparkline draws left-to-right
        // chronological, so reverse to oldest-first.
        const closes = bars.map((b) => Number(b.close)).reverse();
        return [t.ticker, closes] as const;
      } catch {
        return [t.ticker, [] as number[]] as const;
      }
    }),
  );
  const sparklines: Record<string, number[]> =
    Object.fromEntries(sparklineEntries);

  return (
    <main style={{ padding: 24, maxWidth: 1600, margin: "0 auto" }}>
      <header
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "baseline",
          marginBottom: 16,
        }}
      >
        <h1
          style={{
            fontFamily: "var(--font-mono)",
            fontSize: 24,
            letterSpacing: 1,
          }}
        >
          WATCHLIST
        </h1>
        <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
          <span
            style={{
              color: "var(--text-muted)",
              fontSize: 12,
              fontFamily: "var(--font-mono)",
            }}
          >
            {data.scheduler_lag_seconds != null
              ? `scheduler: ${Math.round(data.scheduler_lag_seconds)}s lag`
              : "scheduler: unknown"}
          </span>
          <ScanAllButton />
          <AddTickerDialog />
        </div>
      </header>
      <FilterBar current={sp} />
      <CardGrid data={data} sparklines={sparklines} />
    </main>
  );
}
