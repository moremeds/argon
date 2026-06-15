"use client";

import type { components } from "../types";
import { regimeApi } from "./api";
import { useSyncHook, type UseSyncReturn } from "./useSyncHook";

export type GrgResponse = components["schemas"]["GrgResponse"];
export type GrgAsset = components["schemas"]["GrgAsset"];
export type GrgGate = components["schemas"]["GrgGate"];
export type GrgHistoryEntry = components["schemas"]["GrgHistoryEntry"];
export type GrgEvent = components["schemas"]["GrgEvent"];

export function useGrgLive(): UseSyncReturn<GrgResponse> {
  return useSyncHook<GrgResponse>(
    {
      // GET-only. hasPost MUST stay false: the worker owns UW fetches
      // (15-min RTH job). With hasPost the 60s auto-interval would POST
      // /grg/scan every tick → a synchronous UW rescan PER BROWSER TAB
      // every 60s (the exact failure useCriLive's comment warns about).
      // The page just reads the latest persisted snapshot.
      endpoint: regimeApi.grg(),
      interval: 60_000,
      hasPost: false,
      extractTimestamp: (d) => d.scan_time || null,
      shouldRetry: () => false,
      retryIntervalMs: 60_000,
      retryMethod: "GET",
    },
    true,
  );
}
