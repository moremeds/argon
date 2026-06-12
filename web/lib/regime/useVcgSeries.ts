"use client";

import type { components } from "../types";
import { regimeApi } from "./api";
import { MarketState } from "./useMarketHours";
import { useSyncHook, type UseSyncReturn } from "./useSyncHook";

export type VcgIntradayData = components["schemas"]["VcgIntradayResponse"];
export type VcgIntradayPoint = components["schemas"]["VcgIntradayPoint"];
export type VcgDailyData = components["schemas"]["VcgDailyHistoryResponse"];
export type VcgDailyEntry = components["schemas"]["VcgDailyEntry"];

export function useVcgIntraday(
  marketState: MarketState | null = null,
  sessions: number = 5,
): UseSyncReturn<VcgIntradayData> {
  const active = marketState === MarketState.CLOSED ? false : true;
  return useSyncHook<VcgIntradayData>(
    {
      endpoint: regimeApi.vcg_intraday(sessions),
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

export function useVcgDaily(days: number = 90): UseSyncReturn<VcgDailyData> {
  return useSyncHook<VcgDailyData>(
    {
      endpoint: regimeApi.vcg_history(days),
      interval: 3_600_000,
      hasPost: false,
      extractTimestamp: () => null,
      shouldRetry: () => false,
      retryIntervalMs: 60_000,
      retryMethod: "GET",
    },
    true,
  );
}
