"use client";

import { regimeApi } from "./api";
import { useSyncHook, type UseSyncReturn } from "./useSyncHook";

export type VolBackdropPoint = { date: string; close: number };

export type VolBackdropData = {
  series: Record<"VIX" | "VIX3M" | "VVIX" | "COR1M", VolBackdropPoint[]>;
  term_structure_ratio: number | null;
  term_structure_state: "contango" | "backwardation" | null;
  as_of: string | null;
};

export function useVolBackdrop(): UseSyncReturn<VolBackdropData> {
  return useSyncHook<VolBackdropData>(
    {
      endpoint: regimeApi.vol_backdrop(),
      interval: 3_600_000, // 1h — slow data
      hasPost: false,
      extractTimestamp: (d) => d.as_of,
      shouldRetry: () => false,
      retryIntervalMs: 60_000,
      retryMethod: "GET",
    },
    true,
  );
}
