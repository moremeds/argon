import { api } from "@/lib/api";

export async function TradeInsightsTab({ ticker }: { ticker: string }) {
  const insights = await api.tradeInsights(ticker);
  return (
    <div style={{ display: "grid", gap: 16 }}>
      <h3
        style={{
          fontFamily: "var(--font-mono)",
          fontSize: 9,
          color: "var(--text-muted)",
          letterSpacing: 1,
          textTransform: "uppercase",
        }}
      >
        Trade Insights
      </h3>
      <div
        style={{
          border: "1px solid var(--border-dim)",
          background: "var(--bg-panel)",
          padding: 16,
          fontFamily: "var(--font-mono)",
          fontSize: 12,
        }}
      >
        {insights.header.primary_setup}
      </div>
    </div>
  );
}
