import { notFound } from "next/navigation";
import { api } from "@/lib/api";
import { MarketStructureTab } from "@/components/stock/tabs/MarketStructureTab";
import { VolatilityTab } from "@/components/stock/tabs/VolatilityTab";
import { FlowTab } from "@/components/stock/tabs/FlowTab";
import { TradePlanTab } from "@/components/stock/tabs/TradePlanTab";

const TABS = {
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
  const Component = TABS[tab as keyof typeof TABS];
  if (!Component) notFound();
  const report = await api.stock(ticker);
  return <Component report={report} />;
}
