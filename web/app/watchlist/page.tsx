import { api } from "@/lib/api";
import { CardGrid } from "@/components/watchlist/CardGrid";
import { FilterBar } from "@/components/watchlist/FilterBar";

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

  return (
    <main style={{ padding: "24px", maxWidth: 1600, margin: "0 auto" }}>
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
      </header>
      <FilterBar current={sp} />
      <CardGrid data={data} />
    </main>
  );
}
