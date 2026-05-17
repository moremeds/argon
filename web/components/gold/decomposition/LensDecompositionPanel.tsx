import type { components } from "@/lib/types";

import { HeuristicBadge } from "../chips/HeuristicBadge";

import { DecompositionBars } from "./DecompositionBars";

type Row = components["schemas"]["GoldDecompositionRow"];

export function LensDecompositionPanel({ rows }: { rows: Row[] }) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
      <div
        style={{
          display: "flex",
          alignItems: "baseline",
          gap: 12,
          justifyContent: "space-between",
        }}
      >
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
          LENS DECOMPOSITION · HEURISTIC z
        </h2>
        {/* posture-lint-disable-next-line: explicitly disavowing SHAP, not claiming it */}
        <HeuristicBadge reason="not SHAP — descriptive only" />
      </div>
      <DecompositionBars rows={rows} />
    </div>
  );
}
