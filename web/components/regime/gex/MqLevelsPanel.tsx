"use client";

import { useState } from "react";
import type { CSSProperties, ReactNode } from "react";
import type {
  MqLevels,
  SourceDelta,
  SourceDeltaEntry,
} from "@/lib/regime/useGex";
import { SourceBadge } from "../ui/MetricCard";
import { fmtPrice } from "./format";

export function MqLevelsPanel({
  mq,
  sourceDelta,
}: {
  mq: MqLevels;
  sourceDelta: SourceDelta | null;
}) {
  const [expanded, setExpanded] = useState(false);

  function deltaStyle(d: number | undefined): CSSProperties {
    if (d == null) return {};
    if (Math.abs(d) <= 2) return { color: "var(--signal-core)" };
    if (Math.abs(d) <= 10) return { color: "var(--warning)" };
    return { color: "var(--fault)" };
  }

  function fmtDelta(e: SourceDeltaEntry | undefined): ReactNode {
    if (!e) return <span style={{ color: "var(--text-muted)" }}>—</span>;
    const sign = e.delta > 0 ? "+" : "";
    return (
      <span style={deltaStyle(e.delta)}>
        {sign}
        {e.delta.toFixed(1)} &nbsp;
        <span style={{ color: "var(--signal-core)", fontSize: 9 }}>
          {e.uw.toFixed(0)}
        </span>
        <span style={{ color: "var(--text-muted)", fontSize: 9 }}> vs </span>
        <span style={{ color: "#85b7eb", fontSize: 9 }}>{e.mq.toFixed(0)}</span>
      </span>
    );
  }

  return (
    <div className="gex-history-section">
      <button className="gex-mq-toggle" onClick={() => setExpanded(!expanded)}>
        MenthorQ Key Levels
        {mq.source_date && (
          <span
            style={{
              fontFamily: "var(--font-mono)",
              fontSize: 10,
              color: "var(--text-muted)",
              marginLeft: 8,
            }}
          >
            {mq.source_date}
          </span>
        )}
        <SourceBadge source="mq" /> {expanded ? "▲" : "▼"}
      </button>
      {expanded && (
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "1fr 1fr",
            gap: 16,
            marginTop: 10,
          }}
        >
          <div>
            <div
              style={{
                fontSize: 10,
                letterSpacing: "0.1em",
                textTransform: "uppercase",
                color: "var(--text-muted)",
                marginBottom: 8,
              }}
            >
              Levels
            </div>
            {[
              { label: "HVL (flip)", val: mq.hvl },
              { label: "Call Resistance (all)", val: mq.call_resistance_all },
              { label: "Call Resistance (0DTE)", val: mq.call_resistance_0dte },
              { label: "Put Support (all)", val: mq.put_support_all },
              { label: "Put Support (0DTE)", val: mq.put_support_0dte },
              { label: "Expected High", val: mq.expected_high },
              { label: "Expected Low", val: mq.expected_low },
            ].map(({ label, val }) => (
              <div
                key={label}
                style={{
                  display: "flex",
                  justifyContent: "space-between",
                  fontSize: 11,
                  marginBottom: 5,
                  fontFamily: "var(--font-mono)",
                }}
              >
                <span style={{ color: "var(--text-secondary)", fontSize: 10 }}>
                  {label}
                </span>
                <span style={{ color: "#85b7eb", fontWeight: 500 }}>
                  {val != null ? fmtPrice(val) : "—"}
                </span>
              </div>
            ))}
            {mq.top_gex_strikes.length > 0 && (
              <div style={{ marginTop: 8 }}>
                <div
                  style={{
                    fontSize: 10,
                    color: "var(--text-muted)",
                    marginBottom: 4,
                  }}
                >
                  Top GEX Strikes
                </div>
                <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
                  {mq.top_gex_strikes.map((s) => (
                    <span
                      key={s}
                      style={{
                        background: "rgba(56,138,221,0.12)",
                        color: "#85b7eb",
                        border: "0.5px solid rgba(56,138,221,0.3)",
                        fontSize: 10,
                        padding: "1px 6px",
                        borderRadius: 2,
                        fontFamily: "var(--font-mono)",
                      }}
                    >
                      {fmtPrice(s)}
                    </span>
                  ))}
                </div>
              </div>
            )}
          </div>

          <div>
            <div
              style={{
                fontSize: 10,
                letterSpacing: "0.1em",
                textTransform: "uppercase",
                color: "var(--text-muted)",
                marginBottom: 8,
              }}
            >
              UW vs MQ Delta &nbsp;
              <span
                style={{
                  color: "var(--text-muted)",
                  fontStyle: "italic",
                  textTransform: "none",
                }}
              >
                (+= UW higher)
              </span>
            </div>
            {sourceDelta ? (
              [
                { label: "Flip vs HVL", entry: sourceDelta.flip_vs_hvl },
                {
                  label: "Put wall vs support (all)",
                  entry: sourceDelta.put_wall_vs_support_all,
                },
                {
                  label: "Put wall vs support (0DTE)",
                  entry: sourceDelta.put_wall_vs_support_0dte,
                },
                {
                  label: "Call wall vs resist (all)",
                  entry: sourceDelta.call_wall_vs_resistance_all,
                },
                {
                  label: "Call wall vs resist (0DTE)",
                  entry: sourceDelta.call_wall_vs_resistance_0dte,
                },
              ].map(({ label, entry }) => (
                <div
                  key={label}
                  style={{
                    display: "flex",
                    justifyContent: "space-between",
                    fontSize: 11,
                    marginBottom: 5,
                    fontFamily: "var(--font-mono)",
                  }}
                >
                  <span
                    style={{ color: "var(--text-secondary)", fontSize: 10 }}
                  >
                    {label}
                  </span>
                  {fmtDelta(entry)}
                </div>
              ))
            ) : (
              <div style={{ color: "var(--text-muted)", fontSize: 11 }}>
                No delta data
              </div>
            )}
            {(mq.iv30d != null || mq.hv30 != null) && (
              <div style={{ marginTop: 12 }}>
                <div
                  style={{
                    fontSize: 10,
                    color: "var(--text-muted)",
                    marginBottom: 4,
                  }}
                >
                  Volatility (MQ)
                </div>
                {mq.iv30d != null && (
                  <div
                    style={{
                      display: "flex",
                      justifyContent: "space-between",
                      fontSize: 11,
                      marginBottom: 4,
                      fontFamily: "var(--font-mono)",
                    }}
                  >
                    <span
                      style={{ color: "var(--text-secondary)", fontSize: 10 }}
                    >
                      IV 30D
                    </span>
                    <span style={{ color: "#85b7eb", fontWeight: 500 }}>
                      {(mq.iv30d * 100).toFixed(2)}%
                    </span>
                  </div>
                )}
                {mq.hv30 != null && (
                  <div
                    style={{
                      display: "flex",
                      justifyContent: "space-between",
                      fontSize: 11,
                      fontFamily: "var(--font-mono)",
                    }}
                  >
                    <span
                      style={{ color: "var(--text-secondary)", fontSize: 10 }}
                    >
                      HV 30D
                    </span>
                    <span
                      style={{
                        color: "var(--text-secondary)",
                        fontWeight: 500,
                      }}
                    >
                      {(mq.hv30 * 100).toFixed(2)}%
                    </span>
                  </div>
                )}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
