import type { TradeInsightsResponse } from "@/lib/api";
import { InsightPanel } from "./InsightPanel";

type Row = TradeInsightsResponse["signal_stack"][number];

export function SignalStackPanel({ rows }: { rows: Row[] }) {
  return (
    <InsightPanel heading="SIGNAL STACK">
      <div style={{ display: "grid", gap: 10 }}>
        {rows.map((row) => (
          <div
            key={row.lens}
            style={{
              display: "grid",
              gridTemplateColumns: "96px 1fr",
              gap: 12,
              alignItems: "start",
            }}
          >
            <div
              style={{
                color: "var(--text-muted)",
                fontFamily: "var(--font-mono)",
                fontSize: 11,
              }}
            >
              {row.lens}
            </div>
            <div>
              <div style={{ fontWeight: 600 }}>{row.read}</div>
              <div
                style={{
                  color: "var(--text-secondary)",
                  fontSize: 12,
                  lineHeight: 1.4,
                }}
              >
                {row.evidence.join(" | ")}
              </div>
            </div>
          </div>
        ))}
      </div>
    </InsightPanel>
  );
}
