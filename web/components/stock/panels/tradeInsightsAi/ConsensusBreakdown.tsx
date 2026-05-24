import { Fragment } from "react";

import type { TradeInsightsAiAnalysisResponse } from "@/lib/api";

function headlineField(
  resp: TradeInsightsAiAnalysisResponse | null,
  field: "directional_bias" | "thesis_archetype" | "entry_state",
): string | null {
  const outcome = resp?.outcome as {
    headline?: Record<string, unknown>;
  } | null;
  const value = outcome?.headline?.[field];
  return typeof value === "string" && value.length > 0 ? value : null;
}

export function ConsensusBreakdown({
  codex,
  claude,
}: {
  codex: TradeInsightsAiAnalysisResponse | null;
  claude: TradeInsightsAiAnalysisResponse | null;
}) {
  const rows = (
    [
      ["directional_bias", "Bias"],
      ["thesis_archetype", "Archetype"],
      ["entry_state", "Entry State"],
    ] as const
  )
    .map(([field, label]) => {
      const c = headlineField(codex, field);
      const k = headlineField(claude, field);
      if (c === null || k === null) return null;
      return { field, label, codex: c, claude: k };
    })
    .filter((r): r is NonNullable<typeof r> => r !== null);

  if (rows.length === 0) return null;

  return (
    <div
      data-testid="ai-consensus-breakdown"
      style={{
        border: "1px solid var(--border-dim)",
        borderRadius: 4,
        padding: "10px 12px",
        background: "var(--bg-panel)",
        fontFamily: "var(--font-mono)",
        fontSize: 11,
        color: "var(--text-primary)",
        display: "grid",
        gridTemplateColumns: "minmax(80px, max-content) 1fr min-content 1fr",
        rowGap: 4,
        columnGap: 10,
        alignItems: "center",
      }}
    >
      <div
        style={{
          gridColumn: "1 / -1",
          color: "var(--text-muted)",
          textTransform: "uppercase",
          letterSpacing: 1.2,
          fontSize: 10,
          marginBottom: 2,
        }}
      >
        Codex vs Claude — Headline Decomposition
      </div>
      {rows.map(({ field, label, codex: c, claude: k }) => {
        const matches = c === k;
        const tone = matches ? "var(--positive)" : "var(--warning)";
        return (
          <Fragment key={field}>
            <div style={{ color: "var(--text-muted)" }}>{label}</div>
            <div
              data-testid={`ai-consensus-codex-${field}`}
              style={{ color: "var(--text-primary)" }}
            >
              {c}
            </div>
            <div
              aria-label={matches ? "agree" : "differ"}
              style={{
                color: tone,
                fontWeight: 700,
                padding: "0 6px",
              }}
            >
              {matches ? "=" : "≠"}
            </div>
            <div
              data-testid={`ai-consensus-claude-${field}`}
              style={{ color: "var(--text-primary)" }}
            >
              {k}
            </div>
          </Fragment>
        );
      })}
    </div>
  );
}
