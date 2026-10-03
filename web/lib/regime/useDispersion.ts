"use client";

import { useEffect, useState } from "react";

import { apiFetch } from "@/lib/apiClient";
import type { components } from "@/lib/types";

import { regimeApi } from "./api";

/** Descriptive correlation/dispersion context (EOD, slow-moving). NOT a signal.
 *  Generated from the API's DispersionResponse (I-103). */
export type DispersionData = components["schemas"]["DispersionResponse"];

/** Fetch once on mount, then refresh every 5 min (data updates once/day). */
export function useDispersion(): DispersionData | null {
  const [data, setData] = useState<DispersionData | null>(null);

  useEffect(() => {
    let alive = true;
    const load = async () => {
      try {
        const json = await apiFetch<DispersionData>(regimeApi.dispersion());
        if (alive) setData(json);
      } catch {
        // never-raise: leave the tile row absent rather than break the page
      }
    };
    load();
    const id = setInterval(load, 5 * 60 * 1000);
    return () => {
      alive = false;
      clearInterval(id);
    };
  }, []);

  return data;
}
