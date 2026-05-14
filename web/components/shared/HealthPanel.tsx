"use client";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { fmtDateTimeWithZone } from "@/lib/formatters";
import type { components } from "@/lib/types";

type Health = components["schemas"]["HealthResponse"];
type ProviderSource = "uw" | "massive";

const HEARTBEAT_HEALTHY_LAG_S = 5;

const rowStyle: React.CSSProperties = {
  display: "flex",
  justifyContent: "space-between",
  gap: 8,
  fontFamily: "var(--font-mono)",
  fontSize: 11,
  padding: "3px 0",
  color: "var(--text-muted)",
};
const labelStyle: React.CSSProperties = {
  whiteSpace: "nowrap",
};
const valStyle: React.CSSProperties = {
  color: "var(--text-secondary)",
  whiteSpace: "nowrap",
};
const sourceSelectStyle: React.CSSProperties = {
  background: "transparent",
  border: "1px solid var(--border-dim)",
  color: "var(--text-secondary)",
  fontFamily: "var(--font-mono)",
  fontSize: 11,
  height: 22,
  maxWidth: 150,
  outline: "none",
};

const statusStyle: React.CSSProperties = {
  display: "flex",
  alignItems: "center",
  gap: 6,
};

function dash(v: number | string | null | undefined, suffix = ""): string {
  if (v == null || v === "") return "—";
  return `${v}${suffix}`;
}

function fmtSidebarDateTime(iso: string | null | undefined): string {
  const full = fmtDateTimeWithZone(iso);
  if (full === "—") return full;
  const match = full.match(/^\d{4}\/(\d{2})\/(\d{2}) (\d{2}):(\d{2}):\d{2} (.+)$/);
  if (!match) return full;
  const [, month, day, hour, minute, zone] = match;
  return `${month}/${day} ${hour}:${minute} ${zone}`;
}

function heartbeatStatus(
  lagSeconds: number | null | undefined,
): { label: "ONLINE" | "STALE" | "UNKNOWN"; color: string } {
  if (lagSeconds == null) return { label: "UNKNOWN", color: "var(--warning)" };
  if (lagSeconds <= HEARTBEAT_HEALTHY_LAG_S) {
    return { label: "ONLINE", color: "var(--positive)" };
  }
  return { label: "STALE", color: "var(--warning)" };
}

function StatusRow({
  label,
  status,
}: {
  label: string;
  status: { label: string; color: string };
}) {
  return (
    <div style={rowStyle}>
      <span style={labelStyle}>{label}</span>
      <span style={statusStyle}>
        <span
          style={{
            width: 8,
            height: 8,
            background: status.color,
            display: "inline-block",
          }}
        />
        <span style={valStyle}>{status.label}</span>
      </span>
    </div>
  );
}

export function HealthPanel() {
  const [h, setH] = useState<Health | null>(null);
  const [source, setSource] = useState<ProviderSource>("uw");

  useEffect(() => {
    let cancelled = false;
    const fetchOnce = async () => {
      try {
        const r = await api.health(source);
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
  }, [source]);

  const apiStatus =
    h == null
      ? { label: "OFFLINE", color: "var(--negative)" }
      : { label: "ONLINE", color: "var(--positive)" };
  const schedulerStatus = heartbeatStatus(h?.scheduler_heartbeat_lag_seconds);
  const rescanStatus = heartbeatStatus(h?.rescan_heartbeat_lag_seconds);

  return (
    <div
      style={{
        borderTop: "1px solid var(--border-dim)",
        padding: "12px 16px",
      }}
    >
      <StatusRow label="API" status={apiStatus} />
      <StatusRow label="Scheduler" status={schedulerStatus} />
      <StatusRow label="Rescan" status={rescanStatus} />
      <div style={rowStyle}>
        <span style={labelStyle}>Last Scan</span>
        <span style={valStyle} title={fmtDateTimeWithZone(h?.last_full_scan_at)}>
          {fmtSidebarDateTime(h?.last_full_scan_at)}
        </span>
      </div>
      <div style={rowStyle}>
        <span style={labelStyle}>Source</span>
        <select
          aria-label="Source"
          value={source}
          onChange={(event) => setSource(event.target.value as ProviderSource)}
          style={sourceSelectStyle}
        >
          <option value="uw">UnusualWhales</option>
          <option value="massive">Massive.com</option>
        </select>
      </div>
      <div
        style={{
          borderTop: "1px solid var(--border-dim)",
          margin: "8px 0",
        }}
      />
      <div style={rowStyle}>
        <span style={labelStyle}>Watchlist</span>
        <span style={valStyle}>{dash(h?.watchlist_size)}</span>
      </div>
      <div style={rowStyle}>
        <span style={labelStyle}>Cache Hit</span>
        <span style={valStyle}>{dash(h?.cache_hit_pct, "%")}</span>
      </div>
      <div style={rowStyle}>
        <span style={labelStyle}>Latency p95</span>
        <span style={valStyle}>{dash(h?.latency_p95_ms, "ms")}</span>
      </div>
      <div style={rowStyle}>
        <span style={labelStyle}>2xx</span>
        <span style={valStyle}>{dash(h?.http_2xx)}</span>
      </div>
      <div style={rowStyle}>
        <span style={labelStyle}>4xx</span>
        <span style={valStyle}>{dash(h?.http_4xx)}</span>
      </div>
      <div style={rowStyle}>
        <span style={labelStyle}>5xx</span>
        <span style={valStyle}>{dash(h?.http_5xx)}</span>
      </div>
    </div>
  );
}
