"use client";

import type { components } from "../types";
import { regimeApi } from "./api";
import { useSyncHook, type UseSyncReturn } from "./useSyncHook";

export type VcgLiveResponse = components["schemas"]["VcgLiveResponse"];

export function useVcgLive(): UseSyncReturn<VcgLiveResponse> {
  return useSyncHook<VcgLiveResponse>(
    {
      endpoint: regimeApi.vcg_live(),
      postEndpoint: regimeApi.vcg_scan(),
      interval: 10_000,
      hasPost: true,
      extractTimestamp: (d) => d.scan_time || null,
      shouldRetry: () => false,
      retryIntervalMs: 60_000,
      retryMethod: "POST",
    },
    true,
  );
}
