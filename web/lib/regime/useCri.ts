"use client";

import type { components } from "../types";
import { regimeApi } from "./api";
import { useSyncHook, type UseSyncReturn } from "./useSyncHook";

export type CriResponse = components["schemas"]["CriResponse"];
export type CriBlock = components["schemas"]["CriBlock"];
export type CriComponents = components["schemas"]["CriComponents"];
export type CtaBlock = components["schemas"]["CtaBlock"];
export type CrashTriggerBlock = components["schemas"]["CrashTriggerBlock"];
export type CriHistoryEntry = components["schemas"]["CriHistoryEntry"];

export function useCri(): UseSyncReturn<CriResponse> {
  return useSyncHook<CriResponse>(
    {
      endpoint: regimeApi.cri(),
      // GET reads from /api/regime; manual Sync Now must hit /api/regime/scan.
      postEndpoint: regimeApi.cri_scan(),
      interval: 3_600_000, // 1h — CRI inputs (vol indices + SPY OHLC) update daily
      hasPost: true,
      extractTimestamp: (d) => d.scan_time || null,
      shouldRetry: () => false,
      retryIntervalMs: 60_000,
      retryMethod: "POST",
    },
    true,
  );
}
