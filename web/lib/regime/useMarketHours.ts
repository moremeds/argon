"use client";

import { useState, useEffect } from "react";

/**
 * Market state enum representing different trading time periods in ET.
 * - OPEN: Regular trading hours (9:30 AM - 4:00 PM ET)
 * - EXTENDED: Extended hours (4:00 AM - 9:30 AM OR 4:00 PM - 8:00 PM ET)
 * - CLOSED: Market closed (weekends or 8:00 PM - 4:00 AM ET)
 *
 * Note: This does NOT account for US market holidays. Holidays are rare (~10/year)
 * and not handling them does not introduce resource waste at the target scale.
 */
export enum MarketState {
  OPEN = "open",
  EXTENDED = "extended",
  CLOSED = "closed",
}

/**
 * Hook that returns the current market state based on Eastern Time.
 * Updates every minute (sufficient for market hour boundaries).
 *
 * @returns Current MarketState (OPEN, EXTENDED, or CLOSED)
 */
export function useMarketHours(): MarketState {
  const [state, setState] = useState<MarketState>(MarketState.CLOSED);

  useEffect(() => {
    /**
     * Compute current market state based on ET time.
     */
    const check = () => {
      const now = new Date();
      const et = new Date(
        now.toLocaleString("en-US", { timeZone: "America/New_York" }),
      );
      const day = et.getDay(); // 0=Sun, 6=Sat

      // CLOSED on weekends (Saturdays and Sundays)
      if (day === 0 || day === 6) {
        setState(MarketState.CLOSED);
        return;
      }

      const minutes = et.getHours() * 60 + et.getMinutes();

      // Regular trading hours: 9:30 AM - 4:00 PM ET, half-open interval.
      // IMPORTANT: `< 16*60` (not `<=`) so that at exactly 16:00 we agree
      // with the Python backend's `is_market_open()` which uses the same
      // half-open definition. Without this, frontend and backend disagree
      // for a 60-second window at close and the UI ends up polling a gated
      // backend. See silly-humming-tide.md §4 + Codex issue C4.
      if (minutes >= 9 * 60 + 30 && minutes < 16 * 60) {
        setState(MarketState.OPEN);
      }
      // Extended hours: Premarket (4:00 AM - 9:30 AM) or After Hours
      // (4:00 PM - 8:00 PM). 16:00 now falls into EXTENDED, not OPEN.
      else if (
        (minutes >= 4 * 60 && minutes < 9 * 60 + 30) ||
        (minutes >= 16 * 60 && minutes <= 20 * 60)
      ) {
        setState(MarketState.EXTENDED);
      }
      // Overnight: 8:00 PM - 4:00 AM
      else {
        setState(MarketState.CLOSED);
      }
    };

    // Check immediately on mount
    check();

    // Re-check every minute (sufficient for market hour boundaries)
    const interval = setInterval(check, 60_000);

    return () => clearInterval(interval);
  }, []);

  return state;
}
