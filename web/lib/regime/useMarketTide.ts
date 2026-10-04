"use client";

import type { components } from "@/lib/types";

import { regimeApi } from "./api";
import { MarketState } from "./useMarketHours";
import { useSyncHook, type UseSyncReturn } from "./useSyncHook";

// Generated from the API's MarketTideResponse (I-103b); the names stay.
export type MarketTidePoint = components["schemas"]["MarketTidePoint"];
export type MarketTideSession = components["schemas"]["MarketTideSession"];
export type MarketTideSentiment = components["schemas"]["MarketTideSentiment"];
export type MarketTideData = components["schemas"]["MarketTideResponse"];

// Stable refs — defined once so useSyncHook's executeRequest useCallback does
// not invalidate (and reset the poll interval) on every parent render.
const _extractTs = (d: MarketTideData) => d.as_of as string | null;
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
