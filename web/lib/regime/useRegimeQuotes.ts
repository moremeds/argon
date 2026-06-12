"use client";

import type { components } from "../types";
import { regimeApi } from "./api";
import { useSyncHook, type UseSyncReturn } from "./useSyncHook";

export type RegimeQuotesResponse =
  components["schemas"]["RegimeQuotesResponse"];

// Fallback when the response hasn't arrived yet — matches the backend
// default for REGIME_LIVE_QUOTE_MAX_AGE_SECONDS. The live value comes from
// the response's fresh_within_seconds so client and server can't drift.
const DEFAULT_FRESH_SECONDS = 900;

export function quoteIsFresh(
  quotedAt: string | null | undefined,
  freshWithinSeconds: number = DEFAULT_FRESH_SECONDS,
): boolean {
  if (!quotedAt) return false;
  return Date.now() - new Date(quotedAt).getTime() < freshWithinSeconds * 1000;
}

export function useRegimeQuotes(): UseSyncReturn<RegimeQuotesResponse> {
  return useSyncHook<RegimeQuotesResponse>(
    {
      endpoint: regimeApi.quotes(),
      interval: 2_500, // matches the WS flush cadence + LiveSpotsProvider
      hasPost: false,
      extractTimestamp: (d) => d.as_of ?? null,
      shouldRetry: () => false,
      retryIntervalMs: 10_000,
      retryMethod: "GET",
    },
    true,
  );
}
