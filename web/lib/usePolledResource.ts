"use client";

import { useEffect, useState, type DependencyList } from "react";

export type PollOptions = {
  /** On a failed fetch: keep the last value (default) or reset it to null. */
  onError?: "keep" | "clear";
  /** Skip a tick while the tab is hidden; the next visible tick fetches. */
  skipWhenHidden?: boolean;
  /** Skip a tick while the previous request is still pending. */
  singleFlight?: boolean;
};

/** Fetch on mount (and whenever `deps` change), then every `intervalMs`.
 *  Errors never surface: the caller renders the last value or null (I-107).
 *  A response that lands after unmount or a deps change is dropped. */
export function usePolledResource<T>(
  fetcher: () => Promise<T>,
  intervalMs: number,
  deps: DependencyList,
  {
    onError = "keep",
    skipWhenHidden = false,
    singleFlight = false,
  }: PollOptions = {},
): T | null {
  const [data, setData] = useState<T | null>(null);

  useEffect(() => {
    let cancelled = false;
    let inFlight = false;
    const load = async () => {
      if ((skipWhenHidden && document.hidden) || (singleFlight && inFlight))
        return;
      inFlight = true;
      try {
        const next = await fetcher();
        if (!cancelled) setData(next);
      } catch {
        if (!cancelled && onError === "clear") setData(null);
      } finally {
        inFlight = false;
      }
    };
    void load();
    const id = setInterval(load, intervalMs);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
    // `fetcher` is re-created each render; `deps` names what it closes over.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [intervalMs, onError, skipWhenHidden, singleFlight, ...deps]);

  return data;
}
