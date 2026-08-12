import { notFound } from "next/navigation";
import { api } from "@/lib/api";
import { StockNotReadyDialog } from "@/components/stock/StockNotReadyDialog";
import { MarketStructureTab } from "@/components/stock/tabs/MarketStructureTab";
import { VolatilityTab } from "@/components/stock/tabs/VolatilityTab";
import { SkewTab } from "@/components/stock/tabs/SkewTab";
import { FlowTab } from "@/components/stock/tabs/FlowTab";
import { TradeInsightsTab } from "@/components/stock/tabs/TradeInsightsTab";
import { FrameworkTab } from "@/components/stock/tabs/FrameworkTab";
import { TechnicalsTab } from "@/components/stock/tabs/TechnicalsTab";
import { FundamentalsTab } from "@/components/stock/tabs/FundamentalsTab";
import { isStockReportNotReadyError } from "@/lib/stockNotReady";

const REPORT_TABS = {
  "market-structure": MarketStructureTab,
  volatility: VolatilityTab,
  skew: SkewTab,
  flow: FlowTab,
} as const;

export default async function TabPage({
  params,
}: {
  params: Promise<{ ticker: string; tab: string }>;
}) {
  const { ticker, tab } = await params;
  // Own client island off the SingleStockReport hot path — fetches
  // /api/stock/{ticker}/technicals itself, never the heavy report.
  if (tab === "technicals") {
    return <TechnicalsTab ticker={ticker} />;
  }
  if (tab === "trade-insights") {
    return <TradeInsightsTab ticker={ticker} />;
  }
  // Own client island: reads /api/stock/{ticker}/fundamentals, which is scoped to
  // the tier-1 universe and unrelated to the options report.
  if (tab === "fundamentals") {
    return <FundamentalsTab key={ticker} ticker={ticker} />;
  }
  // The deterministic TradePlanTab was retired in the trade-framework-view
  // work — `trade-plan` now renders the AI-driven FrameworkTab client island
  // (polls per provider; only needs the ticker, no server `report` prop).
  if (tab === "trade-plan") {
    return <FrameworkTab ticker={ticker} />;
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
