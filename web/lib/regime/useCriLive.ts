"use client";

import type { components } from "../types";
import { regimeApi } from "./api";
import { useSyncHook, type UseSyncReturn } from "./useSyncHook";

export type CriLiveResponse = components["schemas"]["CriLiveResponse"];
export type RegimeLiveQuote = components["schemas"]["RegimeLiveQuote"];

export function useCriLive(): UseSyncReturn<CriLiveResponse> {
  return useSyncHook<CriLiveResponse>(
    {
      endpoint: regimeApi.cri_live(),
      // GET recomputes off the latest WS quotes; manual Sync Now still
      // triggers an EOD scan via /api/regime/scan.
      postEndpoint: regimeApi.cri_scan(),
      interval: 10_000, // live recompute off the latest WS quotes
      hasPost: true,
      extractTimestamp: (d) => d.scan_time || null,
      shouldRetry: () => false,
      retryIntervalMs: 60_000,
      retryMethod: "POST",
    },
    true,
  );
}
