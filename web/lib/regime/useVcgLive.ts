"use client";

import type { components } from "../types";
import { regimeApi } from "./api";
import { useSyncHook, type UseSyncReturn } from "./useSyncHook";

export type VcgLiveResponse = components["schemas"]["VcgLiveResponse"];

export function useVcgLive(): UseSyncReturn<VcgLiveResponse> {
  return useSyncHook<VcgLiveResponse>(
    {
      endpoint: regimeApi.vcg_live(),
      // GET-only (see useCriLive) — hasPost would persist an EOD snapshot
      // per 10s tick via /api/regime/vcg/scan.
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
