import type { components } from "@/lib/types";

import { HeuristicBadge } from "../chips/HeuristicBadge";

type C = components["schemas"]["GoldCyclicalPostureModel"];

const zoneLabel: Record<string, string> = {
  "real-rate-driven": "REAL-RATE-DRIVEN",
  "moderate-trap": "MODERATE-TRAP",
  "article-unanchored": "ARTICLE-UNANCHORED",
  transitional: "TRANSITIONAL",
};

export function ArticleZoneCard({ cyclical }: { cyclical: C }) {
  const z = cyclical.zone_label ?? "transitional";
  return (
    <div
      style={{
        padding: 16,
        background: "var(--bg-panel, #0d1018)",
        border: "1px solid var(--border-dim, #1b2030)",
        borderRadius: 4,
        display: "flex",
        flexDirection: "column",
        gap: 8,
      }}
    >
      <div
        style={{
          display: "flex",
          alignItems: "baseline",
          gap: 12,
          justifyContent: "space-between",
        }}
      >
        <span
          style={{
            fontFamily: "var(--font-mono)",
            fontSize: 10,
            letterSpacing: 1.5,
            textTransform: "uppercase",
            color: "var(--text-muted, #6b7280)",
          }}
        >
          ARTICLE ZONE
        </span>
        <HeuristicBadge />
      </div>
      <span
        style={{
          fontFamily: "var(--font-mono)",
          fontSize: 18,
          letterSpacing: 1.5,
          color: "var(--text-primary, #cfd2db)",
        }}
      >
        {zoneLabel[z] ?? z.toUpperCase()}
      </span>
    </div>
  );
}
