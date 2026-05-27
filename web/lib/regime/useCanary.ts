"use client";

import type { components } from "../types";
import { regimeApi } from "./api";
import { useSyncHook, type UseSyncReturn } from "./useSyncHook";

export type CanaryLatestResponse =
  components["schemas"]["CanaryLatestResponse"];
export type CanaryHistoryResponse =
  components["schemas"]["CanaryHistoryResponse"];
export type CanaryValidationResponse =
  components["schemas"]["CanaryValidationResponse"];

export function useCanary(): UseSyncReturn<CanaryLatestResponse> {
  return useSyncHook<CanaryLatestResponse>(
    {
      endpoint: regimeApi.canary(),
      hasPost: false, // no manual /scan endpoint for canary (worker-driven)
    },
    true,
  );
}

export function useCanaryHistory(
  days: number,
): UseSyncReturn<CanaryHistoryResponse> {
  return useSyncHook<CanaryHistoryResponse>(
    {
      endpoint: regimeApi.canaryHistory(days),
      hasPost: false,
    },
    true,
  );
}
