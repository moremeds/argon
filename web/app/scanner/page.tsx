import { CandidateCard } from "@/components/scanner/CandidateCard";
import { DiscoveredCard } from "@/components/scanner/DiscoveredCard";
import { ScannerFilters } from "@/components/scanner/ScannerFilters";
import { QueueProgress } from "@/components/shared/QueueProgress";
import { ScanAllButton } from "@/components/shared/ScanAllButton";
import { api } from "@/lib/api";
import type { components } from "@/lib/types";

export const dynamic = "force-dynamic";

type Candidate = components["schemas"]["ScannerCandidate"];
type Bias = Candidate["bias"];

const SECTION_ORDER: Bias[] = ["bullish", "bearish", "mixed", "neutral"];

const SECTION_TITLE: Record<Bias, string> = {
  bullish: "BULLISH",
  bearish: "BEARISH",
  mixed: "MIXED",
  neutral: "NO DIRECTIONAL READ",
};

const SECTION_COLOR: Record<Bias, string> = {
  bullish: "var(--positive)",
  bearish: "var(--negative)",
  mixed: "var(--warning)",
  neutral: "var(--text-muted)",
};

function groupByBias(candidates: Candidate[]): Map<Bias, Candidate[]> {
  const groups = new Map<Bias, Candidate[]>();
  for (const c of candidates) {
    const arr = groups.get(c.bias) ?? [];
    arr.push(c);
    groups.set(c.bias, arr);
  }
  // Within each section: multi-signal first, then by score desc, then ticker.
  for (const arr of groups.values()) {
    arr.sort(
      (a, b) =>
        Number(b.is_type_f) - Number(a.is_type_f) ||
        Number(b.final_score) - Number(a.final_score) ||
        a.ticker.localeCompare(b.ticker),
    );
  }
  return groups;
}

function latestTimestampMs(values: Array<string | null | undefined>): number {
  let latest = 0;
  for (const value of values) {
    if (!value) continue;
    const parsed = Date.parse(value);
    if (Number.isFinite(parsed)) latest = Math.max(latest, parsed);
  }
  return latest;
}

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
  const hideDiscovered = params.hide_discovered === "true";
  const [data, queue, discover] = await Promise.all([
    api.scanner(qs),
    api.queueSummary().catch(() => undefined),
    hideDiscovered
      ? Promise.resolve(undefined)
      : api.scannerDiscover(20).catch(() => undefined),
  ]);

  const grouped = groupByBias(data.candidates);
  // Single data-derived anchor so server-render and client-hydrate produce
  // identical relative-time labels without reading a clock during render.
  const nowMs = latestTimestampMs([
    ...data.candidates.map((candidate) => candidate.scanned_at),
    ...(discover?.candidates.map((candidate) => candidate.latest_alert_at) ??
      []),
  ]);

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
          SCANNER
        </h1>
        <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
          <QueueProgress queue={queue} />
          <ScanAllButton />
        </div>
      </header>
      <ScannerFilters />
      {discover && discover.candidates.length > 0 ? (
        <section style={{ marginBottom: 28 }}>
          <h2
            style={{
              fontFamily: "var(--font-mono)",
              fontSize: 11,
              letterSpacing: 1.5,
              color: "var(--accent-vol)",
              textTransform: "uppercase",
              marginBottom: 8,
              paddingBottom: 4,
              borderBottom: "1px solid var(--border-dim)",
              display: "flex",
              justifyContent: "space-between",
              alignItems: "baseline",
            }}
          >
            <span>
              DISCOVERED · {discover.candidates.length}{" "}
              <span
                style={{
                  color: "var(--text-muted)",
                  fontSize: 9,
                  letterSpacing: 1,
                }}
              >
                (outside your watchlist · DCF only · pulled from{" "}
                {discover.alerts_pulled} alerts
                {discover.earnings_unknown_dropped > 0
                  ? ` · ${discover.earnings_unknown_dropped} skipped for unknown earnings`
                  : ""}
                )
              </span>
            </span>
          </h2>
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(auto-fill, minmax(320px, 1fr))",
              gap: 12,
            }}
          >
            {discover.candidates.map((c) => (
              <DiscoveredCard key={c.ticker} candidate={c} nowMs={nowMs} />
            ))}
          </div>
        </section>
      ) : null}
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
        SECTION_ORDER.map((bias) => {
          const section = grouped.get(bias);
          if (!section || section.length === 0) return null;
          return (
            <section key={bias} style={{ marginBottom: 28 }}>
              <h2
                style={{
                  fontFamily: "var(--font-mono)",
                  fontSize: 11,
                  letterSpacing: 1.5,
                  color: SECTION_COLOR[bias],
                  textTransform: "uppercase",
                  marginBottom: 8,
                  paddingBottom: 4,
                  borderBottom: "1px solid var(--border-dim)",
                }}
              >
                {SECTION_TITLE[bias]} · {section.length}
              </h2>
              <div
                style={{
                  display: "grid",
                  gridTemplateColumns: "repeat(auto-fill, minmax(320px, 1fr))",
                  gap: 12,
                }}
              >
                {section.map((c) => (
                  <CandidateCard key={c.ticker} candidate={c} nowMs={nowMs} />
                ))}
              </div>
            </section>
          );
        })
      )}
    </div>
  );
}
