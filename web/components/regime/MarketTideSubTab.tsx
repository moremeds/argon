"use client";

import { MarketState } from "@/lib/regime/useMarketHours";
import { useMarketTide } from "@/lib/regime/useMarketTide";
import { MarketTideChart } from "./MarketTideChart";

type Props = { marketState?: MarketState };

export default function MarketTideSubTab({ marketState }: Props) {
  const { data, loading, error, lastSync } = useMarketTide(marketState ?? null);
  const spotTicker = data?.spot_ticker ?? "SPY";

  return (
    <div
      style={{ display: "flex", flexDirection: "column", gap: 16 }}
      data-testid="market-tide-subtab"
    >
      <p
        style={{
          margin: 0,
          fontSize: 12,
          lineHeight: 1.6,
          color: "var(--text-muted)",
          maxWidth: 760,
        }}
      >
        Market-wide net call vs. put option premium across the whole US options
        tape, in 5-min buckets. Each line is the running net premium for that
        session — calls (green) pulling above puts (red) reads bullish/risk-on;
        puts above calls reads defensive/hedging. {spotTicker} spot is overlaid
        in gold; net volume sits in the lower band.
      </p>

      {error && (
        <div className="section" data-testid="market-tide-error">
          <div className="section-body" style={{ padding: 16, fontSize: 11 }}>
            <span style={{ color: "var(--negative)" }}>
              Failed to load market tide:
            </span>{" "}
            <span style={{ color: "var(--text-muted)" }}>{error}</span>
          </div>
        </div>
      )}

      {loading && !data ? (
        <div className="section" data-testid="market-tide-loading">
          <div
            className="section-body"
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
        </div>
      ) : (
        <MarketTideChart data={data} />
      )}

      {lastSync && (
        <div
          style={{
            fontFamily: "var(--font-mono)",
            fontSize: 10,
            color: "var(--text-muted)",
            letterSpacing: "0.06em",
          }}
        >
          LAST SYNC {new Date(lastSync).toLocaleTimeString()}
        </div>
      )}
    </div>
  );
}
