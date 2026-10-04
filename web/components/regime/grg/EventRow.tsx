"use client";

import { formatSignedNumber } from "../primitives/format";
import { type GrgEvent } from "@/lib/regime/useGrgLive";
import { fmtGex, pairStateColor, shortState, sigmaColor } from "./format";

export function EventRow({ ev }: { ev: GrgEvent }) {
  return (
    <div
      data-testid="grg-event-row"
      style={{
        padding: "8px 0",
        borderBottom: "1px solid var(--border-dim)",
      }}
    >
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "auto 64px 1fr auto",
          gap: 8,
          alignItems: "baseline",
          fontFamily: "var(--font-mono)",
          fontSize: 12,
        }}
      >
        <span style={{ color: "var(--text-secondary)" }}>{ev.date}</span>
        <span
          style={{
            color: sigmaColor(ev.grg_z),
            textAlign: "right",
            fontWeight: 700,
          }}
        >
          {formatSignedNumber(ev.grg_z)}
          {ev.grg_z != null ? "σ" : ""}
        </span>
        <span
          style={{
            color: pairStateColor(ev.pair_state),
            letterSpacing: "0.5px",
          }}
        >
          {shortState(ev.pair_state)}
        </span>
        <span style={{ color: "var(--text-muted)" }}>
          {ev.tier != null ? `T${ev.tier}` : "—"}
        </span>
      </div>
      <div
        style={{
          fontFamily: "var(--font-mono)",
          fontSize: 10,
          color: "var(--text-muted)",
          marginTop: 2,
        }}
      >
        SPY {fmtGex(ev.spy_net_gamma)} · TLT {fmtGex(ev.tlt_net_gamma)}
        {ev.lead_sessions != null && ev.extreme_gap_pct != null ? (
          <span style={{ color: "var(--text-secondary)" }}>
            {` · led ${ev.lead_sessions}d, SPY ${
              ev.extreme_gap_pct >= 0 ? "+" : ""
            }${ev.extreme_gap_pct.toFixed(1)}% to extreme`}
          </span>
        ) : null}
      </div>
    </div>
  );
}
