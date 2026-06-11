"use client";

import { regimeApi } from "./api";
import { MarketState } from "./useMarketHours";
import { useSyncHook, type UseSyncReturn } from "./useSyncHook";

export type GexIntradayPoint = {
  ts: string;
  spot: number | null;
  net_gex: number | null;
  gex_flip: number | null;
  iv30d: number | null;
};

export type GexIntradaySession = {
  et_date: string;
  points: GexIntradayPoint[];
};

export type GexIntradayData = {
  ticker: string;
  sessions: GexIntradaySession[];
  as_of: string | null;
};

export function useGexIntraday(
  marketState: MarketState | null = null,
  ticker: string = "SPX",
  sessions: number = 5,
): UseSyncReturn<GexIntradayData> {
  // Same activity rules as useGex — the dataset moves only when the GEX
  // scanner ticks, and that's gated on market state in the worker.
  const active =
    marketState === MarketState.CLOSED ? false : true;

  const config = {
    endpoint: regimeApi.gex_intraday(ticker, sessions),
    interval: marketState === MarketState.EXTENDED ? 300_000 : 60_000,
    hasPost: false,
    extractTimestamp: (d: GexIntradayData) => d.as_of,
    shouldRetry: () => false,
    retryIntervalMs: 5000,
    retryMethod: "GET" as const,
  };

  return useSyncHook<GexIntradayData>(config, active);
}
