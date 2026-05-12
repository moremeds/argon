"use client";
import Link from "next/link";
import type { components } from "@/lib/types";

type Card = components["schemas"]["WatchlistCard"];

export function TickerCard({ card }: { card: Card }) {
  return (
    <Link
      href={`/stock/${card.ticker}`}
      style={{
        display: "block",
        padding: 12,
        background: "var(--bg-panel)",
        border: "1px solid var(--border-dim)",
        borderRadius: 4,
        color: "var(--text-primary)",
        textDecoration: "none",
        fontFamily: "var(--font-mono)",
      }}
    >
      <div style={{ fontSize: 16, fontWeight: 700 }}>{card.ticker}</div>
      <div style={{ fontSize: 11, color: "var(--text-muted)" }}>
        {card.sector}
      </div>
      <div style={{ fontSize: 10, color: "var(--text-muted)", marginTop: 8 }}>
        scanned: {new Date(card.scanned_at).toLocaleTimeString()}
      </div>
    </Link>
  );
}
