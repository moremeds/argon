import { CardGrid } from "@/components/watchlist/CardGrid";
import { FilterBar } from "@/components/watchlist/FilterBar";
import {
  buildSectorGroups,
  chainCounts,
} from "@/components/watchlist/sectorGroups";
import { AddTickerDialog } from "@/components/watchlist/AddTickerDialog";
import { QueueProgress } from "@/components/shared/QueueProgress";
import { ScanAllButton } from "@/components/shared/ScanAllButton";
import { loadDashboardData } from "@/lib/dashboardData";

// Skip the Router Cache so sector/setup chip clicks refetch with new
// searchParams instead of reusing the unfiltered RSC payload.
export const dynamic = "force-dynamic";

export default async function DashboardPage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | undefined>>;
}) {
  const sp = await searchParams;
  const qs = new URLSearchParams();
  if (sp.sector) qs.set("sector", sp.sector);
  if (sp.chain) qs.set("chain", sp.chain);
  if (sp.setup) qs.set("setup", sp.setup);
  if (sp.fresh) qs.set("fresh_within_minutes", sp.fresh);
  const { data, chains, apiUnavailable } = await loadDashboardData(qs);
  const groups = buildSectorGroups(chains);

  return (
    <div style={{ padding: 24, maxWidth: 1600, margin: "0 auto" }}>
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
          DASHBOARD
        </h1>
        <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
          <QueueProgress queue={data.queue} />
          <ScanAllButton />
          <AddTickerDialog chains={chains} />
        </div>
      </header>
      {apiUnavailable && (
        <div
          style={{
            marginBottom: 12,
            padding: "10px 12px",
            border: "1px solid var(--border-dim)",
            background: "var(--bg-panel)",
            color: "var(--warning)",
            fontFamily: "var(--font-mono)",
            fontSize: 11,
          }}
        >
          API unavailable. Start-up is still warming; refresh when the API is
          ready.
        </div>
      )}
      <FilterBar current={sp} groups={groups} counts={chainCounts(chains)} />
      <CardGrid data={data} />
    </div>
  );
}
