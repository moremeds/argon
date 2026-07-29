import { DiscoveredCard } from "@/components/scanner/DiscoveredCard";
import {
  type Bias,
  SECTION_COLOR,
  SECTION_ORDER,
  SECTION_TITLE,
} from "@/components/scanner/bias";
import type { components } from "@/lib/types";

export const dynamic = "force-dynamic";

type Discovered = components["schemas"]["DiscoveryCandidate"];
type DiscoverResponse =
  | Awaited<ReturnType<typeof import("@/lib/api").api.scannerDiscover>>
  | undefined;

function groupDiscoveredByBias(
  candidates: Discovered[],
): Map<Bias, Discovered[]> {
  const groups = new Map<Bias, Discovered[]>();
  for (const c of candidates) {
    const arr = groups.get(c.bias) ?? [];
    arr.push(c);
    groups.set(c.bias, arr);
  }
  // Within each section: highest edge-quality score first, then ticker.
  for (const arr of groups.values()) {
    arr.sort(
      (a, b) =>
        Number(b.score) - Number(a.score) || a.ticker.localeCompare(b.ticker),
    );
  }
  return groups;
}

/** Tickers OUTSIDE the watchlist surfaced by the market-wide flow-alerts feed.

Its own tab rather than a section inside Flow: it answers a different question
(what should I be looking at that I am not?) and is ranked by edge quality
rather than by the full Dark Pool / EIC / GEX scan the Flow tab reports.
*/
export default function DiscoverSubTab({
  discover,
}: {
  // Fetched by the route so the tab badge is correct before this tab is opened.
  discover: DiscoverResponse;
}) {
  if (!discover || discover.candidates.length === 0) {
    return (
      <div
        style={{
          padding: 24,
          border: "1px dashed var(--border-dim)",
          borderRadius: 4,
          color: "var(--text-muted)",
          fontFamily: "var(--font-mono)",
          fontSize: 12,
        }}
      >
        No discovered tickers in the latest scored snapshot.
      </div>
    );
  }
  const discoverGrouped = groupDiscoveredByBias(discover.candidates);
  const scoredAtMs = discover.scored_at ? Date.parse(discover.scored_at) : NaN;
  const nowMs = Number.isFinite(scoredAtMs) ? scoredAtMs : 0;

  return (
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
            (edge-quality · DP-confirmed · {discover.alerts_pulled} alerts
            {discover.earnings_unknown_dropped > 0
              ? ` · ${discover.earnings_unknown_dropped} skipped for unknown earnings`
              : ""}
            {discover.scored_at
              ? ` · scored ${new Date(
                  discover.scored_at,
                ).toLocaleTimeString([], {
                  hour: "2-digit",
                  minute: "2-digit",
                })}`
              : ""}
            )
          </span>
        </span>
      </h2>
      {SECTION_ORDER.map((bias) => {
        const section = discoverGrouped.get(bias);
        if (!section || section.length === 0) return null;
        return (
          <div key={bias} style={{ marginBottom: 16 }}>
            <h3
              style={{
                fontFamily: "var(--font-mono)",
                fontSize: 10,
                letterSpacing: 1.2,
                color: SECTION_COLOR[bias],
                textTransform: "uppercase",
                marginBottom: 6,
              }}
            >
              {SECTION_TITLE[bias]} · {section.length}
            </h3>
            <div
              style={{
                display: "grid",
                gridTemplateColumns:
                  "repeat(auto-fill, minmax(320px, 1fr))",
                gap: 12,
              }}
            >
              {section.map((c) => (
                <DiscoveredCard
                  key={c.ticker}
                  candidate={c}
                  nowMs={nowMs}
                />
              ))}
            </div>
          </div>
        );
      })}
    </section>
  );
}
