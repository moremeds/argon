"use client";

import type { components } from "../types";
import { regimeApi } from "./api";
import { useSyncHook, type UseSyncReturn } from "./useSyncHook";

export type VcgResponse = components["schemas"]["VcgResponse"];
export type VcgSignal = components["schemas"]["VcgSignal"];
export type VcgHistoryEntry = components["schemas"]["VcgHistoryEntry"];
export type VcgAttribution = components["schemas"]["VcgAttribution"];

export function useVcg(): UseSyncReturn<VcgResponse> {
  return useSyncHook<VcgResponse>(
    {
      endpoint: regimeApi.vcg(),
      // GET reads /api/regime/vcg; Sync Now must hit /api/regime/vcg/scan.
      postEndpoint: regimeApi.vcg_scan(),
      interval: 3_600_000, // 1h — VCG inputs (VIX / VVIX / credit OHLC) are daily
      hasPost: true,
      extractTimestamp: (d) => d.scan_time || null,
      shouldRetry: () => false,
      retryIntervalMs: 60_000,
      retryMethod: "POST",
    },
    true,
  );
}
