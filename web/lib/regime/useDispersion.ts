"use client";

import { useEffect, useState } from "react";

import { regimeApi } from "./api";

/** Descriptive correlation/dispersion context (EOD, slow-moving). NOT a signal. */
export interface DispersionData {
  as_of: string | null;
  cor1m: number | null;
  cor1m_percentile: number | null; // 0–1
  vix: number | null;
  vix_cor1m_ratio: number | null;
  vix_cor1m_ratio_z: number | null; // trailing-252
  history_start: string | null;
  n_obs: number;
}

/** Fetch once on mount, then refresh every 5 min (data updates once/day). */
export function useDispersion(): DispersionData | null {
  const [data, setData] = useState<DispersionData | null>(null);

  useEffect(() => {
    let alive = true;
    const load = async () => {
      try {
        const res = await fetch(regimeApi.dispersion());
        if (!res.ok) return;
        const json = (await res.json()) as DispersionData;
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
