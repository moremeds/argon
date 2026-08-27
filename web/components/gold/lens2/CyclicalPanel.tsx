import type { components } from "@/lib/types";

import { PostureChip, type PostureState } from "../chips/PostureChip";

import { ArticleZoneCard } from "./ArticleZoneCard";
import { GprCard } from "./GprCard";
import { InfExpCard } from "./InfExpCard";
import { RealRateCard } from "./RealRateCard";
import { UsdTrendCard } from "./UsdTrendCard";

type C = components["schemas"]["GoldCyclicalPostureModel"];

export function CyclicalPanel({ cyclical }: { cyclical: C }) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      <div
        style={{
          display: "flex",
          alignItems: "baseline",
          gap: 12,
          justifyContent: "space-between",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
          <h2
            style={{
              fontFamily: "var(--font-mono)",
              fontSize: 12,
              letterSpacing: 1.8,
              textTransform: "uppercase",
              color: "var(--text-primary, #cfd2db)",
              margin: 0,
            }}
          >
            LENS 2 · CYCLICAL POSTURE
          </h2>
          <PostureChip
            state={(cyclical.posture_chip ?? "NEUTRAL") as PostureState}
          />
        </div>
        <span
          style={{
            fontFamily: "var(--font-mono)",
            fontSize: 10,
            letterSpacing: 1.5,
            textTransform: "uppercase",
            color: "var(--text-muted, #6b7280)",
          }}
        >
          B POSTURE CONTEXT (event-hedge)
        </span>
      </div>

      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(4, minmax(0, 1fr))",
          gap: 12,
        }}
      >
        <RealRateCard cyclical={cyclical} />
        <UsdTrendCard cyclical={cyclical} />
        <GprCard cyclical={cyclical} />
        <InfExpCard cyclical={cyclical} />
      </div>

      <ArticleZoneCard cyclical={cyclical} />

      <p
        style={{
          fontFamily: "var(--font-mono)",
          fontSize: 11,
          lineHeight: 1.5,
          color: "var(--text-secondary, #9aa3b2)",
          margin: 0,
        }}
      >
        {cyclical.narrative_text}
      </p>
    </div>
  );
}
