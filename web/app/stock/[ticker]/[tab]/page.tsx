import { notFound } from "next/navigation";
import { api } from "@/lib/api";
import { StockNotReadyDialog } from "@/components/stock/StockNotReadyDialog";
import { MarketStructureTab } from "@/components/stock/tabs/MarketStructureTab";
import { VolatilityTab } from "@/components/stock/tabs/VolatilityTab";
import { FlowTab } from "@/components/stock/tabs/FlowTab";
import { TradeInsightsTab } from "@/components/stock/tabs/TradeInsightsTab";
import { TradePlanTab } from "@/components/stock/tabs/TradePlanTab";
import { isStockReportNotReadyError } from "@/lib/stockNotReady";

const REPORT_TABS = {
  "market-structure": MarketStructureTab,
  volatility: VolatilityTab,
  flow: FlowTab,
  "trade-plan": TradePlanTab,
} as const;

export default async function TabPage({
  params,
}: {
  params: Promise<{ ticker: string; tab: string }>;
}) {
  const { ticker, tab } = await params;
  if (tab === "trade-insights") {
    return <TradeInsightsTab ticker={ticker} />;
  }
  const Component = REPORT_TABS[tab as keyof typeof REPORT_TABS];
  if (!Component) notFound();

  let report;
  try {
    report = await api.stock(ticker);
  } catch (error) {
    if (isStockReportNotReadyError(error, ticker)) {
      return <StockNotReadyDialog ticker={ticker} />;
    }
    throw error;
  }
  return <Component report={report} />;
}
