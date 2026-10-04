"use client";

import type { components } from "@/lib/types";

import { regimeApi } from "./api";
import { MarketState } from "./useMarketHours";
import { useSyncHook, type UseSyncReturn } from "./useSyncHook";

/* ─── GEX types (mirror xenon's gex_scan.py JSON output) ─────── */

// Generated from the API's GexResponse (I-103b); the names stay.
export type GexLevel = components["schemas"]["RegimeGexLevel"] | null;
export type GexBucket = components["schemas"]["GexBucket"];
export type GexBias = components["schemas"]["GexBias"];
export type GexHistoryEntry = components["schemas"]["GexHistoryEntry"];
export type MqLevels = components["schemas"]["GexMqLevels"];
export type SourceDeltaEntry = components["schemas"]["GexSourceDeltaEntry"];
export type SourceDelta = components["schemas"]["GexSourceDelta"];
export type IvData = components["schemas"]["GexIvData"];
export type GexData = components["schemas"]["GexResponse"];

/* ─── Staleness check ────────────────────────────────────────── */

function todayET(): string {
  return new Date().toLocaleDateString("sv", {
    timeZone: "America/New_York",
  });
}

function needsGexRetry(data: GexData | null | undefined): boolean {
  if (!data?.scan_time) return true;
  try {
    const scanDate = new Date(data.scan_time).toLocaleDateString("sv", {
      timeZone: "America/New_York",
    });
    return scanDate !== todayET();
  } catch {
    return true;
  }
}

/* ─── Hook ───────────────────────────────────────────────────── */

export function useGex(
  marketState: MarketState | null = null,
  ticker: string = "SPX",
): UseSyncReturn<GexData> {
  let active: boolean;
  if (
    marketState === MarketState.OPEN ||
    marketState === MarketState.EXTENDED
  ) {
    active = true;
  } else if (marketState === MarketState.CLOSED) {
    active = false;
  } else {
    active = true;
  }

  const config = {
    endpoint: regimeApi.gex(ticker),
    interval: marketState === MarketState.EXTENDED ? 300_000 : 60_000,
    hasPost: false,
    extractTimestamp: (d: GexData) => d.scan_time || null,
    shouldRetry: (d: GexData) => needsGexRetry(d),
    retryIntervalMs: 5000,
    retryMethod: "GET" as const,
  };

  return useSyncHook<GexData>(config, active);
}
