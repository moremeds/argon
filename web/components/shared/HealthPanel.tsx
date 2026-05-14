"use client";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { fmtDateTimeWithZone } from "@/lib/formatters";
import type { components } from "@/lib/types";

type Health = components["schemas"]["HealthResponse"];

// Worker is considered healthy if its last heartbeat is within this window.
// rescan_tick fires every 1s, so anything > 5s means the loop is stalled.
const WORKER_HEALTHY_LAG_S = 5;

const rowStyle: React.CSSProperties = {
  display: "flex",
  justifyContent: "space-between",
  fontFamily: "var(--font-mono)",
  fontSize: 11,
  padding: "3px 0",
  color: "var(--text-muted)",
};
const valStyle: React.CSSProperties = {
  color: "var(--text-secondary)",
};

function dash(v: number | string | null | undefined, suffix = ""): string {
  if (v == null || v === "") return "—";
  return `${v}${suffix}`;
}

export function HealthPanel() {
  const [h, setH] = useState<Health | null>(null);

  useEffect(() => {
    let cancelled = false;
    const fetchOnce = async () => {
      try {
        const r = await api.health();
        if (!cancelled) setH(r);
      } catch {
        if (!cancelled) setH(null);
      }
    };
    fetchOnce();
    const t = setInterval(fetchOnce, 5000);
    return () => {
      cancelled = true;
      clearInterval(t);
    };
  }, []);

  const workerOnline =
    h?.worker_lag_seconds != null &&
    h.worker_lag_seconds <= WORKER_HEALTHY_LAG_S;
  const workerColor = workerOnline ? "var(--positive)" : "var(--negative)";
  const workerLabel =
    h?.worker_lag_seconds == null
      ? "UNKNOWN"
      : workerOnline
        ? "ONLINE"
        : "OFFLINE";

  return (
    <div
      style={{
        borderTop: "1px solid var(--border-dim)",
        padding: "12px 16px",
      }}
    >
      <div style={rowStyle}>
        <span>Worker</span>
        <span style={{ display: "flex", alignItems: "center", gap: 6 }}>
          <span
            style={{
              width: 8,
              height: 8,
              background: workerColor,
              display: "inline-block",
            }}
          />
          <span style={valStyle}>{workerLabel}</span>
        </span>
      </div>
      <div style={rowStyle}>
        <span>Last Scan</span>
        <span style={valStyle}>{fmtDateTimeWithZone(h?.last_full_scan_at)}</span>
      </div>
      <div style={rowStyle}>
        <span>Source</span>
        <span style={valStyle}>{h?.source ?? "massive.com"}</span>
      </div>
      <div
        style={{
          borderTop: "1px solid var(--border-dim)",
          margin: "8px 0",
        }}
      />
      <div style={rowStyle}>
        <span>Watchlist</span>
        <span style={valStyle}>{dash(h?.watchlist_size)}</span>
      </div>
      <div style={rowStyle}>
        <span>Cache Hit</span>
        <span style={valStyle}>{dash(h?.cache_hit_pct, "%")}</span>
      </div>
      <div style={rowStyle}>
        <span>Latency p95</span>
        <span style={valStyle}>{dash(h?.latency_p95_ms, "ms")}</span>
      </div>
      <div style={rowStyle}>
        <span>2xx</span>
        <span style={valStyle}>{dash(h?.http_2xx)}</span>
      </div>
      <div style={rowStyle}>
        <span>4xx</span>
        <span style={valStyle}>{dash(h?.http_4xx)}</span>
      </div>
      <div style={rowStyle}>
        <span>5xx</span>
        <span style={valStyle}>{dash(h?.http_5xx)}</span>
      </div>
    </div>
  );
}
