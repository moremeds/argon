"use client";

import { apiFetch } from "@/lib/apiClient";
import { usePolledResource } from "@/lib/usePolledResource";
import type { components } from "@/lib/types";

import { regimeApi } from "./api";

/** Descriptive correlation/dispersion context (EOD, slow-moving). NOT a signal.
 *  Generated from the API's DispersionResponse (I-103). */
export type DispersionData = components["schemas"]["DispersionResponse"];

/** Fetch once on mount, then refresh every 5 min (data updates once/day). */
export function useDispersion(): DispersionData | null {
  // never-raise: on error the tile row stays absent rather than break the page
  return usePolledResource(
    () => apiFetch<DispersionData>(regimeApi.dispersion()),
    5 * 60 * 1000,
    [],
  );
}
