import { api } from "@/lib/api";
import { CandidateStructuresPanel } from "../panels/CandidateStructuresPanel";
import { ChainFlowReadPanel } from "../panels/ChainFlowReadPanel";
import { InsightsSynthesisPanel } from "../panels/InsightsSynthesisPanel";
import { SignalStackPanel } from "../panels/SignalStackPanel";
import { SourceReconciliationPanel } from "../panels/SourceReconciliationPanel";
import { TermMovePanel } from "../panels/TermMovePanel";
import { TradeInsightsAiAnalysisPanel } from "../panels/TradeInsightsAiAnalysisPanel";
import { TradeInsightsBiasBanner } from "../panels/TradeInsightsBiasBanner";

const upperPairGridStyle = {
  display: "grid",
  gridTemplateColumns: "repeat(2, minmax(0, 1fr))",
  alignItems: "stretch",
  gridAutoRows: "1fr",
  gap: 12,
};

const lowerPairGridStyle = {
  display: "grid",
  gridTemplateColumns: "minmax(0, 1.15fr) minmax(0, 0.85fr)",
  alignItems: "stretch",
  gridAutoRows: "1fr",
  gap: 12,
};

export async function TradeInsightsTab({ ticker }: { ticker: string }) {
  const insights = await api.tradeInsights(ticker);
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      <TradeInsightsBiasBanner header={insights.header} />
      <TradeInsightsAiAnalysisPanel ticker={ticker} />
      <div data-testid="trade-insights-upper-pair" style={upperPairGridStyle}>
        <ChainFlowReadPanel rows={insights.flow_table} />
        <TermMovePanel rows={insights.term_structure_table} />
      </div>
      <InsightsSynthesisPanel synthesis={insights.synthesis} />
      <div data-testid="trade-insights-lower-pair" style={lowerPairGridStyle}>
        <SourceReconciliationPanel reconciliation={insights.source_reconciliation} />
        <SignalStackPanel rows={insights.signal_stack} />
      </div>
      <CandidateStructuresPanel candidates={insights.candidate_structures} />
    </div>
  );
}
