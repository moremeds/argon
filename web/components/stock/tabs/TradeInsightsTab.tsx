import { api } from "@/lib/api";
import { CandidateStructuresPanel } from "../panels/CandidateStructuresPanel";
import { ChainFlowReadPanel } from "../panels/ChainFlowReadPanel";
import { InsightsSynthesisPanel } from "../panels/InsightsSynthesisPanel";
import { SignalStackPanel } from "../panels/SignalStackPanel";
import { SourceReconciliationPanel } from "../panels/SourceReconciliationPanel";
import { TermMovePanel } from "../panels/TermMovePanel";
import { TradeInsightsAiAnalysisPanel } from "../panels/TradeInsightsAiAnalysisPanel";
import { TradeInsightsBiasBanner } from "../panels/TradeInsightsBiasBanner";

export async function TradeInsightsTab({ ticker }: { ticker: string }) {
  const insights = await api.tradeInsights(ticker);
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 18 }}>
      <TradeInsightsBiasBanner header={insights.header} />
      <TradeInsightsAiAnalysisPanel ticker={ticker} />
      <div
        className="trade-insights-evidence-grid"
        data-testid="trade-insights-evidence-grid"
      >
        <ChainFlowReadPanel rows={insights.flow_table} />
        <TermMovePanel rows={insights.term_structure_table} />
        <SourceReconciliationPanel reconciliation={insights.source_reconciliation} />
        <SignalStackPanel rows={insights.signal_stack} />
      </div>
      <InsightsSynthesisPanel synthesis={insights.synthesis} />
      <CandidateStructuresPanel candidates={insights.candidate_structures} />
    </div>
  );
}
