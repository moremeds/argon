import { CandidateTile } from "@/components/scanner/CandidateTile";
import { GatedList } from "@/components/scanner/GatedList";
import { ScannerFilters } from "@/components/scanner/ScannerFilters";
import { api } from "@/lib/api";

export const dynamic = "force-dynamic";

export default async function ScannerPage({
  searchParams,
}: {
  searchParams: Promise<{ [key: string]: string | string[] | undefined }>;
}) {
  const params = await searchParams;
  const qs = new URLSearchParams();
  if (params.type_f_only === "true") qs.set("type_f_only", "true");
  if (params.tier_1_only === "true") qs.set("tier_1_only", "true");
  if (typeof params.sector === "string") qs.set("sector", params.sector);
  const data = await api.scanner(qs);

  return (
    <div style={{ padding: 24, maxWidth: 1600, margin: "0 auto" }}>
      <h1
        style={{
          fontFamily: "var(--font-mono)",
          fontSize: 24,
          letterSpacing: 1,
          marginBottom: 16,
        }}
      >
        SCANNER
      </h1>
      <ScannerFilters />
      {data.candidates.length === 0 ? (
        <div
          style={{
            padding: 24,
            border: "1px dashed var(--border-dim)",
            borderRadius: 4,
            color: "var(--text-muted)",
            fontFamily: "var(--font-mono)",
            fontSize: 12,
            textAlign: "center",
          }}
        >
          no candidates — {data.scanned_universe_size} ticker
          {data.scanned_universe_size === 1 ? "" : "s"} on watchlist, none with
          recent scanner-producing scans
        </div>
      ) : (
        data.candidates.map((c) => (
          <CandidateTile key={c.ticker} candidate={c} />
        ))
      )}
      <GatedList gated={data.gated} />
    </div>
  );
}
