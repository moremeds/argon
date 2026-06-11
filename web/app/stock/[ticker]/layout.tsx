import { api } from "@/lib/api";
import { DetailHeader } from "@/components/stock/DetailHeader";
import { StockNotReadyDialog } from "@/components/stock/StockNotReadyDialog";
import { TabBar } from "@/components/stock/TabBar";
import { LiveSpotsProvider } from "@/components/watchlist/LiveSpotsProvider";
import { toNum } from "@/lib/formatters";
import { isStockReportNotReadyError } from "@/lib/stockNotReady";

export default async function StockLayout({
  children,
  params,
}: {
  children: React.ReactNode;
  params: Promise<{ ticker: string }>;
}) {
  const { ticker } = await params;
  let report;
  try {
    report = await api.stock(ticker);
  } catch (error) {
    if (isStockReportNotReadyError(error, ticker)) {
      return <StockNotReadyDialog ticker={ticker} />;
    }
    throw error;
  }

  return (
    <div style={{ minHeight: "100%", background: "var(--bg-base)" }}>
      {/* One spots poller for the whole detail page: the header and any
          spot-anchored panels (GEX tiles/profile) consume useLiveSpot. */}
      <LiveSpotsProvider>
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
      </LiveSpotsProvider>
    </div>
  );
}
