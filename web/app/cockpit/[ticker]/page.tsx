import Link from "next/link";
import { api } from "@/lib/api";
import { CockpitTabs } from "./CockpitTabs";

export const dynamic = "force-dynamic";

const COCKPIT_TICKERS = ["SPX", "SPY", "QQQ", "IWM"] as const;

export default async function CockpitStatePage({
  params,
  searchParams,
}: {
  params: Promise<{ ticker: string }>;
  searchParams: Promise<{ asof?: string }>;
}) {
  const { ticker } = await params;
  const { asof } = await searchParams;
  const t = ticker.toUpperCase();
  const [stateData, dealerData, surfaceData, flowImData, vrpData] =
    await Promise.all([
      api.cockpitState(t, asof),
      api.cockpitDealer(t, asof),
      api.cockpitSurface(t, asof),
      api.cockpitFlowIm(t, asof),
      api.cockpitVrp(t, asof),
    ]);

  return (
    <div
      style={{
        minHeight: "100%",
        background: "var(--bg-base)",
        padding: 24,
      }}
    >
      <header
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          gap: 16,
          marginBottom: 18,
        }}
      >
        <div>
          <div
            style={{
              color: "var(--text-muted)",
              fontFamily: "var(--font-mono)",
              fontSize: 11,
              letterSpacing: 1.5,
              textTransform: "uppercase",
            }}
          >
            Cockpit
          </div>
          <h1
            style={{
              margin: 0,
              color: "var(--text-primary)",
              fontFamily: "var(--font-mono)",
              fontSize: 28,
              letterSpacing: 0,
            }}
          >
            {t}
          </h1>
        </div>
        <nav style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
          {COCKPIT_TICKERS.map((symbol) => (
            <Link
              key={symbol}
              href={`/cockpit/${symbol}`}
              style={{
                minWidth: 46,
                padding: "8px 10px",
                border: "1px solid var(--border-dim)",
                background:
                  symbol === t ? "var(--bg-panel-raised)" : "var(--bg-panel)",
                color:
                  symbol === t ? "var(--accent-bg)" : "var(--text-secondary)",
                fontFamily: "var(--font-mono)",
                fontSize: 12,
                textAlign: "center",
                textDecoration: "none",
              }}
            >
              {symbol}
            </Link>
          ))}
        </nav>
      </header>
      <CockpitTabs
        ticker={t}
        stateData={stateData}
        dealerData={dealerData}
        surfaceData={surfaceData}
        flowImData={flowImData}
        vrpData={vrpData}
      />
    </div>
  );
}
