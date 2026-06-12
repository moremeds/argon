"use client";

import type { components } from "../types";
import { regimeApi } from "./api";
import { useSyncHook, type UseSyncReturn } from "./useSyncHook";

export type RegimeQuotesResponse =
  components["schemas"]["RegimeQuotesResponse"];

const FRESH_MS = 15 * 60 * 1000;

export function quoteIsFresh(quotedAt: string | null | undefined): boolean {
  if (!quotedAt) return false;
  return Date.now() - new Date(quotedAt).getTime() < FRESH_MS;
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
