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
      // GET-only: every poll IS a live recompute server-side. hasPost MUST
      // stay false — with hasPost the interval would POST /api/regime/scan
      // every 10s, persisting an EOD snapshot per tick (Codex P1). EOD
      // scans stay worker-owned; Sync Now just refreshes the live read.
      interval: 10_000,
      hasPost: false,
      extractTimestamp: (d) => d.scan_time || null,
      shouldRetry: () => false,
      retryIntervalMs: 60_000,
      retryMethod: "GET",
    },
    true,
  );
}
