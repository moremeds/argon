"use client";

import { regimeApi } from "./api";
import { useSyncHook, type UseSyncReturn } from "./useSyncHook";

export type SpxDensityHorizon = {
  h: number;
  target_date: string;
  scored_horizon: boolean;
  q05: number;
  q10: number;
  q25: number;
  q50: number;
  q75: number;
  q90: number;
  q95: number;
  baseline_q05: number;
  baseline_q10: number;
  baseline_q25: number;
  baseline_q50: number;
  baseline_q75: number;
  baseline_q90: number;
  baseline_q95: number;
  band80_width: number;
  baseline_band80_width: number;
  width_ratio: number;
  realised_return: number | null;
  inside_band80: boolean | null;
};

export type SpxDensityForecast = {
  as_of: string;
  anchor_close: number;
  origin: string;
  fallback_used: boolean;
  params: Record<string, number> | null;
  rows: SpxDensityHorizon[];
};

export type SpxDensityHitRate = {
  origin: string;
  inside: number;
  total: number;
};

export type SpxDensityLatest = {
  forecast: SpxDensityForecast | null;
  recent_path: { date: string; close: number }[];
  disclaimer: string;
};

export type SpxDensityIssued = {
  forecasts: SpxDensityForecast[];
  hit_rates: SpxDensityHitRate[];
};

// Stable refs so useSyncHook's executeRequest useCallback never invalidates.
const _latestTs = (d: SpxDensityLatest) => d.forecast?.as_of ?? null;
const _issuedTs = (d: SpxDensityIssued) => d.forecasts[0]?.as_of ?? null;
const _noRetry = () => false;

// Data changes once per night — 5-min polling is plenty.
const _INTERVAL = 300_000;

export function useSpxDensity(): UseSyncReturn<SpxDensityLatest> {
  return useSyncHook<SpxDensityLatest>(
    {
      endpoint: regimeApi.spx_density(),
      interval: _INTERVAL,
      hasPost: false,
      extractTimestamp: _latestTs,
      shouldRetry: _noRetry,
      retryIntervalMs: 5000,
      retryMethod: "GET" as const,
    },
    true,
  );
}

export function useSpxDensityIssued(): UseSyncReturn<SpxDensityIssued> {
  return useSyncHook<SpxDensityIssued>(
    {
      endpoint: regimeApi.spx_density_issued(5),
      interval: _INTERVAL,
      hasPost: false,
      extractTimestamp: _issuedTs,
      shouldRetry: _noRetry,
      retryIntervalMs: 5000,
      retryMethod: "GET" as const,
    },
    true,
  );
}
