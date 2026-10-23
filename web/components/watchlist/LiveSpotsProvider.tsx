"use client";
import {
  createContext,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from "react";
import type { components } from "@/lib/types";
import { API_BASE } from "@/lib/apiClient";

type WatchlistSpot = components["schemas"]["WatchlistSpot"];
type WatchlistSpotsResponse = components["schemas"]["WatchlistSpotsResponse"];

export type LiveSpotsMap = Map<string, WatchlistSpot>;

// Default null = no provider mounted (unit tests, non-dashboard pages):
// consumers fall back to the server-rendered spot.
const LiveSpotsContext = createContext<LiveSpotsMap | null>(null);

export function useLiveSpot(ticker: string): WatchlistSpot | null {
  const spots = useContext(LiveSpotsContext);
  return spots?.get(ticker) ?? null;
}

export const SPOTS_STREAM_PATH = "/api/watchlist/spots/stream";
const STREAM_STALE_MS = 5000; // the API pings every 2 s

/** One stream for the whole page — ticks every card's spot in place without
 * an RSC refresh. The WS consumer (xenon primary / massive fallback) flushes
 * every ~0.25 s and NOTIFYs; the API pushes only the tickers that changed
 * (the first event after connect carries all of them), so each event merges
 * into the map. EventSource reconnects on its own after a drop. */
export function LiveSpotsProvider({ children }: { children: ReactNode }) {
  const [spots, setSpots] = useState<LiveSpotsMap | null>(null);

  useEffect(() => {
    // jsdom (component tests) has no EventSource: keep the server-rendered spots.
    if (typeof EventSource === "undefined") return;
    let source: EventSource | null = null;
    let lastSeen = 0;
    const close = () => {
      source?.close();
      source = null;
    };
    const open = () => {
      const stream = new EventSource(`${API_BASE}${SPOTS_STREAM_PATH}`);
      source = stream;
      lastSeen = Date.now();
      stream.onmessage = (event: MessageEvent<string>) => {
        lastSeen = Date.now();
        const rows =
          (JSON.parse(event.data) as WatchlistSpotsResponse).spots ?? [];
        setSpots((prev) => {
          const next = new Map(prev ?? []);
          for (const row of rows) next.set(row.ticker, row);
          return next;
        });
      };
      stream.addEventListener("ping", () => {
        lastSeen = Date.now();
      });
    };
    // One watchdog for every quiet death: EventSource gives up for good
    // (CLOSED) when a re-dial gets the proxy's 5xx while the API restarts,
    // and a killed API can leave the Next proxy holding the browser's half
    // open with nothing on it. The API pings every 2 s, so silence = dead.
    const watchdog = setInterval(() => {
      if (document.hidden) return;
      if (
        !source ||
        source.readyState === EventSource.CLOSED ||
        Date.now() - lastSeen > STREAM_STALE_MS
      ) {
        close();
        open();
      }
    }, 1000);
    // A hidden tab drops its stream (nobody is looking, and a browser caps
    // open HTTP/1.1 connections per host); showing it again reconnects and
    // the first event resyncs every ticker.
    const onVisibility = () => {
      if (document.hidden) close();
      else if (!source) open();
    };
    if (!document.hidden) open();
    document.addEventListener("visibilitychange", onVisibility);
    return () => {
      document.removeEventListener("visibilitychange", onVisibility);
      clearInterval(watchdog);
      close();
    };
  }, []);

  return (
    <LiveSpotsContext.Provider value={spots}>
      {children}
    </LiveSpotsContext.Provider>
  );
}
