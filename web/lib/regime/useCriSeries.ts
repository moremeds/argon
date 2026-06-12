"use client";

import type { components } from "../types";
import { regimeApi } from "./api";
import { MarketState } from "./useMarketHours";
import { useSyncHook, type UseSyncReturn } from "./useSyncHook";

export type CriIntradayData = components["schemas"]["CriIntradayResponse"];
export type CriIntradayPoint = components["schemas"]["CriIntradayPoint"];
export type CriDailyData = components["schemas"]["CriDailyHistoryResponse"];
export type CriDailyEntry = components["schemas"]["CriDailyEntry"];

export function useCriIntraday(
  marketState: MarketState | null = null,
  sessions: number = 5,
): UseSyncReturn<CriIntradayData> {
  const active = marketState === MarketState.CLOSED ? false : true;
  return useSyncHook<CriIntradayData>(
    {
      endpoint: regimeApi.cri_intraday(sessions),
      interval: marketState === MarketState.EXTENDED ? 300_000 : 60_000,
      hasPost: false,
      extractTimestamp: (d) => d.as_of ?? null,
      shouldRetry: () => false,
      retryIntervalMs: 5000,
      retryMethod: "GET",
    },
    active,
  );
}

export function useCriDaily(days: number = 90): UseSyncReturn<CriDailyData> {
  return useSyncHook<CriDailyData>(
    {
      endpoint: regimeApi.cri_history(days),
      interval: 3_600_000, // daily rows only move on the hourly EOD scan
      hasPost: false,
      extractTimestamp: () => null,
      shouldRetry: () => false,
      retryIntervalMs: 60_000,
      retryMethod: "GET",
    },
    true,
  );
}
