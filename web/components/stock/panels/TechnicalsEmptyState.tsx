"use client";

import { useState } from "react";
import { api, type TechnicalsResponse } from "@/lib/api";

// Shown when a ticker has no EOD technicals yet. "Compute now" runs the same
// job the nightly refresh runs, scoped to this one ticker (~3s: apex bars +
// pandas), then hands the fresh payload back so the tab re-renders in place.
// For a watchlist ticker this also makes it eligible for the 5-min live overlay
// on the next tick (the live scan skips tickers with < 210 daily bars).
export function TechnicalsEmptyState({
  ticker,
  onComputed,
}: {
  ticker: string;
  onComputed: (data: TechnicalsResponse) => void;
}) {
  const [computing, setComputing] = useState(false);
  const [note, setNote] = useState<string | null>(null);

  async function handleCompute() {
    setComputing(true);
    setNote(null);
    try {
      const fresh = await api.technicalsRefresh(ticker);
      if (fresh.backfill_status === "ready") {
        onComputed(fresh);
      } else {
        setNote(
          `No daily history available for ${ticker} (thin history or apex unreachable).`,
        );
      }
    } catch (err) {
      setNote(`Compute failed: ${String(err)}`);
    } finally {
      setComputing(false);
    }
  }

  return (
    <div
      style={{
        color: "var(--text-muted)",
        padding: 16,
        display: "flex",
        flexDirection: "column",
        gap: 12,
        alignItems: "flex-start",
      }}
    >
      <div>
        No technicals history for {ticker} yet — populated by the nightly
        refresh, or compute it now.
      </div>
      <button
        type="button"
        onClick={handleCompute}
        disabled={computing}
        style={{
          fontSize: 10,
          fontFamily: "var(--font-mono)",
          textTransform: "uppercase",
          letterSpacing: 1,
          padding: "4px 10px",
          background: "transparent",
          color: computing ? "var(--text-muted)" : "var(--text-secondary)",
          border: "1px solid var(--border-dim)",
          borderRadius: 2,
          cursor: computing ? "default" : "pointer",
        }}
      >
        {computing ? "Computing… (~3s)" : "Compute now"}
      </button>
      {note ? <div style={{ color: "var(--warning)" }}>{note}</div> : null}
    </div>
  );
}
