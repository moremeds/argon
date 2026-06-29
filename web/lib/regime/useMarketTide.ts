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

export type MarketTideSentiment = {
  state: string; // BULLISH | BEARISH | BALANCED | WARMING_UP
  magnitude: string; // FLAT | LEANING | STRONG
  driver: string;
  momentum: string;
  spread: number | null;
  session_slope: number | null; // $/hr
  recent_slope: number | null; // $/hr
  trend_strength: number | null;
  volume_confirms: boolean | null;
  bars: number;
};

export type MarketTideData = {
  sessions: MarketTideSession[];
  spot_ticker: string | null;
  as_of: string | null;
  market_open: boolean;
  sentiment: MarketTideSentiment | null;
};

// Stable refs — defined once so useSyncHook's executeRequest useCallback does
// not invalidate (and reset the poll interval) on every parent render.
const _extractTs = (d: MarketTideData) => d.as_of;
const _noRetry = () => false;

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
    extractTimestamp: _extractTs,
    shouldRetry: _noRetry,
    retryIntervalMs: 5000,
    retryMethod: "GET" as const,
  };

  return useSyncHook<MarketTideData>(config, active);
}
