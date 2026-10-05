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

// Module-level so their identity is stable: inline arrows would change on
// every render, re-create useSyncHook's request callback and re-arm (never
// fire) the 60 s interval each time the quotes poll re-renders the tab.
const _extractTs = (d: GexData) => d.scan_time || null;
const _noRetry = () => false;

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
    extractTimestamp: _extractTs,
    // Retry a stale scan only while the scanner can produce a new one. The
    // retry timer runs even when inactive, so off-hours it would re-run the
    // history query every 5 s for as long as the tab stays open.
    shouldRetry:
      marketState === MarketState.OPEN || marketState === MarketState.EXTENDED
        ? needsGexRetry
        : _noRetry,
    retryIntervalMs: 5000,
    retryMethod: "GET" as const,
  };

  return useSyncHook<GexData>(config, active);
}
