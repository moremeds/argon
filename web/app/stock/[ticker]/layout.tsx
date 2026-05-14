import { api } from "@/lib/api";
import { DetailHeader } from "@/components/stock/DetailHeader";
import { TabBar } from "@/components/stock/TabBar";
import { toNum } from "@/lib/formatters";

export default async function StockLayout({
  children,
  params,
}: {
  children: React.ReactNode;
  params: Promise<{ ticker: string }>;
}) {
  const { ticker } = await params;
  const report = await api.stock(ticker);

  return (
    <div style={{ minHeight: "100%", background: "var(--bg-base)" }}>
      <DetailHeader
        ticker={report.ticker}
        spot={toNum(report.market_structure.spot)}
        iv_atm={toNum(report.volatility.iv)}
        spotQuotedAt={report.spot_quoted_at ?? null}
        scannedAt={report.generated_at}
        setupType={report.setup?.setup_type ?? null}
        setupDirection={report.setup?.direction ?? null}
        setupScore={toNum(report.setup?.score)}
      />
      <TabBar ticker={ticker} />
      <div style={{ padding: 16 }}>{children}</div>
    </div>
  );
}
