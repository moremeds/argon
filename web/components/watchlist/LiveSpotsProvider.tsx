"use client";
import {
  createContext,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from "react";
import type { components } from "@/lib/types";
import { api } from "@/lib/api";

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
  const [spots, setSpots] = useState<LiveSpotsMap | null>(null);

  useEffect(() => {
    let cancelled = false;
    const fetchOnce = async () => {
      // Skip while the tab is hidden — no point hammering the API for a
      // page nobody is looking at; resumes on the next visible tick.
      if (document.hidden) return;
      try {
        const res = await api.watchlistSpots();
        if (cancelled) return;
        setSpots(new Map((res.spots ?? []).map((s) => [s.ticker, s])));
      } catch {
        // Transient fetch failure: keep the last map (or the server-rendered
        // values); the next tick retries.
      }
    };
    fetchOnce();
    const t = setInterval(fetchOnce, POLL_MS);
    return () => {
      cancelled = true;
      clearInterval(t);
    };
  }, []);

  return (
    <LiveSpotsContext.Provider value={spots}>
      {children}
    </LiveSpotsContext.Provider>
  );
}
