import { api } from "@/lib/api";
import { SignalStackPanel } from "../panels/SignalStackPanel";
import { SourceReconciliationPanel } from "../panels/SourceReconciliationPanel";
import { TradeInsightsBiasBanner } from "../panels/TradeInsightsBiasBanner";

export async function TradeInsightsTab({ ticker }: { ticker: string }) {
  const insights = await api.tradeInsights(ticker);
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      <TradeInsightsBiasBanner header={insights.header} />
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
        <SourceReconciliationPanel reconciliation={insights.source_reconciliation} />
        <SignalStackPanel rows={insights.signal_stack} />
      </div>
    </div>
  );
}
