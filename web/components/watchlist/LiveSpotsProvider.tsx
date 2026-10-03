"use client";
import { createContext, useContext, type ReactNode } from "react";
import type { components } from "@/lib/types";
import { api } from "@/lib/api";
import { usePolledResource } from "@/lib/usePolledResource";

type WatchlistSpot = components["schemas"]["WatchlistSpot"];

export type LiveSpotsMap = Map<string, WatchlistSpot>;

// Default null = no provider mounted (unit tests, non-dashboard pages):
// consumers fall back to the server-rendered spot.
const LiveSpotsContext = createContext<LiveSpotsMap | null>(null);

export function useLiveSpot(ticker: string): WatchlistSpot | null {
  const spots = useContext(LiveSpotsContext);
  return spots?.get(ticker) ?? null;
}

const POLL_MS = 2500; // matches QueueProgress's active cadence; WS flushes ~1s

/** One poller for the whole card grid — ticks every card's spot in place
 * without an RSC refresh. The WS consumer (xenon primary / massive fallback)
 * rewrites watchlist_card.spot ~1/s; /api/watchlist/spots is the lightweight
 * projection of just (ticker, spot, quoted_at, source). */
export function LiveSpotsProvider({ children }: { children: ReactNode }) {
  // Skip while the tab is hidden (nobody is looking) and while a request is
  // still pending; a failed tick keeps the last map (or the server-rendered
  // values) and the next tick retries.
  // ponytail: a fetch that never settles parks polling until reload — add
  // AbortSignal.timeout on the client if that ever bites.
  const spots = usePolledResource<LiveSpotsMap>(
    async () => {
      const res = await api.watchlistSpots();
      return new Map((res.spots ?? []).map((s) => [s.ticker, s]));
    },
    POLL_MS,
    [],
    { skipWhenHidden: true, singleFlight: true },
  );

  return (
    <LiveSpotsContext.Provider value={spots}>
      {children}
    </LiveSpotsContext.Provider>
  );
}
