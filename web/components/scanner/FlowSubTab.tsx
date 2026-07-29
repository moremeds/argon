import { CandidateCard } from "@/components/scanner/CandidateCard";
import {
  type Bias,
  SECTION_COLOR,
  SECTION_ORDER,
  SECTION_TITLE,
} from "@/components/scanner/bias";
import { ScannerFilters } from "@/components/scanner/ScannerFilters";
import { QueueProgress } from "@/components/shared/QueueProgress";
import { ScanAllButton } from "@/components/shared/ScanAllButton";
import type { components } from "@/lib/types";

export const dynamic = "force-dynamic";

type Candidate = components["schemas"]["ScannerCandidate"];
type ScannerResponse = Awaited<ReturnType<typeof import("@/lib/api").api.scanner>>;
type QueueSummary = Awaited<
  ReturnType<typeof import("@/lib/api").api.queueSummary>
> | undefined;

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

export default async function FlowSubTab({
  data,
  queue,
}: {
  // Fetched by the route, not here: the tab strip needs the candidate count for
  // its badge even when Flow is not the active tab, and the route is the only
  // place that can supply it without a second api.scanner round-trip.
  data: ScannerResponse;
  queue: QueueSummary;
}) {
  const grouped = groupByBias(data.candidates);
  // API-generated render anchor so freshness is relative to request time while
  // client hydration receives the same value and does not read a clock.
  const generatedAtMs = Date.parse(data.generated_at);
  const nowMs = Number.isFinite(generatedAtMs) ? generatedAtMs : 0;

  return (
    <div>
      <header
        style={{
          display: "flex",
          justifyContent: "flex-end",
          alignItems: "center",
          gap: 12,
          marginBottom: 16,
        }}
      >
        <QueueProgress queue={queue} />
        <ScanAllButton />
      </header>
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
