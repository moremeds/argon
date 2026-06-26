"use client";

import { regimeApi } from "./api";
import { MarketState } from "./useMarketHours";
import { useSyncHook, type UseSyncReturn } from "./useSyncHook";

export type MarketTidePoint = {
  ts: string;
  net_call_premium: number | null;
  net_put_premium: number | null;
  net_volume: number | null;
  spot: number | null;
};

export type MarketTideSession = {
  date: string;
  points: MarketTidePoint[];
};

export type MarketTideData = {
  sessions: MarketTideSession[];
  spot_ticker: string | null;
  as_of: string | null;
  market_open: boolean;
};

export function useMarketTide(
  marketState: MarketState | null = null,
  sessions: number = 5,
): UseSyncReturn<MarketTideData> {
  // The worker captures market-tide every 5 min through RTH, so there's no
  // point polling faster than that while open, and nothing moves once closed.
  const active = marketState === MarketState.CLOSED ? false : true;

  const config = {
    endpoint: regimeApi.market_tide(sessions),
    interval: marketState === MarketState.EXTENDED ? 300_000 : 60_000,
    hasPost: false,
    extractTimestamp: (d: MarketTideData) => d.as_of,
    shouldRetry: () => false,
    retryIntervalMs: 5000,
    retryMethod: "GET" as const,
  };

  return useSyncHook<MarketTideData>(config, active);
}
