"use client";

import { regimeApi } from "./api";
import { MarketState } from "./useMarketHours";
import { useSyncHook, type UseSyncReturn } from "./useSyncHook";

export type TopNetImpactRow = {
  ticker: string;
  net_premium: number | null;
  rank: number | null;
  prev_rank: number | null;
  rank_change: number | null; // prev_rank - rank; +climbed, null = new this session
};

export type TopNetImpactData = {
  rows: TopNetImpactRow[];
  data_date: string | null;
};

const _extractTs = (d: TopNetImpactData) =>
  d.data_date ? `${d.data_date}:${d.rows[0]?.ticker ?? ""}` : null;
const _noRetry = () => false;

export function useTopNetImpact(
  marketState: MarketState | null = null,
  limit: number = 24,
): UseSyncReturn<TopNetImpactData> {
  // Worker captures every 15 min through RTH; nothing moves once closed.
  const active = marketState === MarketState.CLOSED ? false : true;

  const config = {
    endpoint: regimeApi.top_net_impact(limit),
    interval: marketState === MarketState.EXTENDED ? 300_000 : 60_000,
    hasPost: false,
    extractTimestamp: _extractTs,
    shouldRetry: _noRetry,
    retryIntervalMs: 5000,
    retryMethod: "GET" as const,
  };

  return useSyncHook<TopNetImpactData>(config, active);
}
