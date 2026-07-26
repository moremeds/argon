"use client";

import type { components } from "../types";
import { regimeApi } from "./api";
import { MarketState } from "./useMarketHours";
import { useSyncHook, type UseSyncReturn } from "./useSyncHook";

// Aliased from the generated contract, never hand-declared -- the convention
// every other regime hook follows (useCri.ts:7-12). Hand-writing a parallel
// shape here would silently drift from the API the first time a field changes,
// which is exactly the bug web/CLAUDE.md warns about.
export type SectorCrowdingLeg = components["schemas"]["SectorCrowdingLeg"];
export type SectorCrowdingSeriesPoint =
  components["schemas"]["SectorCrowdingSeriesPoint"];
export type SectorCrowdingRow = components["schemas"]["SectorCrowdingRow"];
export type SectorCrowdingData =
  components["schemas"]["SectorCrowdingResponse"];
export type CrowdingBand = NonNullable<SectorCrowdingRow["state"]>;
export type LegName = NonNullable<SectorCrowdingRow["binding_leg"]>;

const _extractTs = (d: SectorCrowdingData) => d.as_of ?? null;
const _noRetry = () => false;

export function useSectorCrowding(
  marketState: MarketState | null = null,
): UseSyncReturn<SectorCrowdingData> {
  // Captured once nightly at 18:45 ET; nothing moves intraday. Poll slowly
  // just to pick up the new session after the job runs.
  const config = {
    endpoint: regimeApi.sector_crowding(),
    interval: 900_000,
    hasPost: false,
    extractTimestamp: _extractTs,
    shouldRetry: _noRetry,
    retryIntervalMs: 5000,
    retryMethod: "GET" as const,
  };

  return useSyncHook<SectorCrowdingData>(config, marketState !== null);
}
