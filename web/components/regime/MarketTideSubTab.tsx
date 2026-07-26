"use client";

import { Activity } from "lucide-react";
import { MarketState } from "@/lib/regime/useMarketHours";
import { useMarketTide } from "@/lib/regime/useMarketTide";
import { useSectorCrowding } from "@/lib/regime/useSectorCrowding";
import { useTopNetImpact } from "@/lib/regime/useTopNetImpact";
import InfoTooltip from "./InfoTooltip";
import { SectorCrowdingPanel } from "./SectorCrowdingPanel";
import { MarketTideChart } from "./MarketTideChart";
import { MarketTideDailyChart } from "./MarketTideDailyChart";
import { TideSentimentBanner } from "./TideSentimentBanner";
import { TopNetImpactChart } from "./TopNetImpactChart";

type Props = { marketState?: MarketState };

const GUIDE =
  "Daily aggregated option premium & volume. Net premium = $ traded at/near " +
  "the ask minus $ at/near the bid, for calls and puts separately. Calls bought " +
  "at the ask read bullish; puts bought at the ask read bearish. Lines close & " +
  "parallel = balanced sentiment; diverging = sentiment intensifying — bullish " +
  "if call premium rises faster or put premium falls faster, bearish if the " +
  "reverse. Net volume = (ask−bid) call volume minus (ask−bid) put volume; read " +
  "premium alongside volume.";

export default function MarketTideSubTab({ marketState }: Props) {
  const { data, loading, error, lastSync } = useMarketTide(marketState ?? null);
  const { data: tni } = useTopNetImpact(marketState ?? null);
  const { data: crowding } = useSectorCrowding(marketState ?? null);
  const spotTicker = data?.spot_ticker ?? "SPY";

  // The latest captured session is "today" once the market opens (the worker
  // captures it live) and the previous business day before then — so the daily
  // chart shifts automatically with no explicit market-open branch. The strip
  // below shows the earlier sessions for context.
  const sessions = data?.sessions ?? [];
  const latest = sessions.length ? sessions[sessions.length - 1] : null;
  const priorData = data ? { ...data, sessions: sessions.slice(0, -1) } : null;

  return (
    <div className="section" data-testid="market-tide-subtab">
      <div className="section-header">
        <div className="section-title">
          <Activity size={14} />
          Market Tide{latest ? ` — ${latest.date}` : ""}
          <InfoTooltip
            text={GUIDE}
            triggerTestId="market-tide-section-tooltip-trigger"
            contentTestId="market-tide-section-tooltip-content"
          />
        </div>
        {lastSync && (
          <span
            style={{
              fontFamily: "var(--font-mono)",
              fontSize: 10,
              color: "var(--text-muted)",
            }}
          >
            {new Date(lastSync).toLocaleTimeString()}
          </span>
        )}
      </div>

      <div
        className="section-body"
        style={{ display: "flex", flexDirection: "column", gap: 16 }}
      >
        {error && (
          <div data-testid="market-tide-error" style={{ fontSize: 11 }}>
            <span style={{ color: "var(--negative)" }}>
              Failed to load market tide:
            </span>{" "}
            <span style={{ color: "var(--text-muted)" }}>{error}</span>
          </div>
        )}

        {loading && !data ? (
          <div
            data-testid="market-tide-loading"
            style={{
              padding: 24,
              textAlign: "center",
              color: "var(--text-muted)",
              fontFamily: "var(--font-mono)",
              fontSize: 11,
            }}
          >
            Loading market tide…
          </div>
        ) : (
          <>
            <TideSentimentBanner sentiment={data?.sentiment ?? null} />
            {/* Daily tide (image-6 layout) on the left, Top Net Impact on the
                right. minmax(0,…) keeps both columns from overflowing. */}
            <div
              style={{
                display: "grid",
                gridTemplateColumns: "minmax(0, 1.6fr) minmax(0, 1fr)",
                gap: 16,
                alignItems: "stretch",
              }}
            >
              <MarketTideDailyChart session={latest} spotTicker={spotTicker} />
              <TopNetImpactChart data={tni} />
            </div>
            {priorData && priorData.sessions.length > 0 && (
              <MarketTideChart data={priorData} />
            )}
            <SectorCrowdingPanel data={crowding} />
          </>
        )}
      </div>
    </div>
  );
}
