import type { components } from "@/lib/types";

type Gated = components["schemas"]["ScannerGatedTicker"];

function reasonText(g: Gated): string {
  if (g.reason === "stale_scan") {
    return "stale scan (older than freshness window)";
  }
  if (g.reason === "regime_block") {
    return g.blocking_chip
      ? `regime block (structural posture: ${g.blocking_chip})`
      : "regime block";
  }
  return g.reason;
}

export function GatedList({ gated }: { gated: Gated[] }) {
  if (gated.length === 0) return null;
  return (
    <div style={{ marginTop: 24 }}>
      <div
        style={{
          fontFamily: "var(--font-mono)",
          fontSize: 10,
          letterSpacing: 1.5,
          color: "var(--text-muted)",
          textTransform: "uppercase",
          marginBottom: 8,
        }}
      >
        GATED ({gated.length} watchlist ticker
        {gated.length === 1 ? "" : "s"} excluded)
      </div>
      <div
        style={{
          padding: 16,
          backgroundColor: "var(--bg-panel)",
          border: "1px solid var(--border-dim)",
          borderRadius: 4,
        }}
      >
        {gated.map((g) => (
          <div
            key={g.ticker}
            style={{
              display: "flex",
              justifyContent: "space-between",
              fontFamily: "var(--font-mono)",
              fontSize: 12,
              color: "var(--text-muted)",
              padding: "4px 0",
            }}
          >
            <span style={{ color: "var(--text-primary)" }}>{g.ticker}</span>
            <span>{reasonText(g)}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
