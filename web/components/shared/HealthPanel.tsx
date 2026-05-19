"use client";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { fmtDateTimeWithZone } from "@/lib/formatters";
import type { components } from "@/lib/types";

type Health = components["schemas"]["HealthResponse"];
type WorkerHealth = NonNullable<Health["workers"]>[number];
type ProviderSource = "uw" | "massive";

const HEARTBEAT_HEALTHY_LAG_S = 5;
const SPOT_REFRESH_HEALTHY_LAG_S = 660;
const RECORD_WINDOW_HOURS = 8;
const RECORD_MIN_COVERAGE = 0.9;
const COLLAPSED_STORAGE_KEY = "uw_health_collapsed";

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
  const match = full.match(
    /^\d{4}\/(\d{2})\/(\d{2}) (\d{2}):(\d{2}):\d{2} (.+)$/,
  );
  if (!match) return full;
  const [, month, day, hour, minute, zone] = match;
  return `${month}/${day} ${hour}:${minute} ${zone}`;
}

function heartbeatStatus(
  lagSeconds: number | null | undefined,
  healthyLagSeconds = HEARTBEAT_HEALTHY_LAG_S,
): { label: "ONLINE" | "STALE" | "UNKNOWN"; color: string } {
  if (lagSeconds == null) return { label: "UNKNOWN", color: "var(--warning)" };
  if (lagSeconds <= healthyLagSeconds) {
    return { label: "ONLINE", color: "var(--positive)" };
  }
  return { label: "STALE", color: "var(--warning)" };
}

function recordHealthStatus(ok: boolean | null | undefined): {
  label: "OK" | "ALERT" | "UNKNOWN";
  color: string;
} {
  if (ok == null) return { label: "UNKNOWN", color: "var(--warning)" };
  if (ok) return { label: "OK", color: "var(--positive)" };
  return { label: "ALERT", color: "var(--negative)" };
}

function workerGroupStatus(workers: WorkerHealth[]): {
  label: string;
  color: string;
} {
  if (workers.length === 0)
    return { label: "UNKNOWN", color: "var(--warning)" };
  const online = workers.filter((worker) => {
    const healthyLag =
      worker.role === "massive"
        ? SPOT_REFRESH_HEALTHY_LAG_S
        : HEARTBEAT_HEALTHY_LAG_S;
    return heartbeatStatus(worker.lag_seconds, healthyLag).label === "ONLINE";
  }).length;
  if (online === workers.length) {
    return { label: `${online}/${workers.length}`, color: "var(--positive)" };
  }
  if (online === 0) {
    return { label: `${online}/${workers.length}`, color: "var(--negative)" };
  }
  return { label: `${online}/${workers.length}`, color: "var(--warning)" };
}

function fmtDuration(seconds: number | null | undefined): string {
  if (seconds == null) return "—";
  const s = Math.max(0, Math.round(seconds));
  if (s < 60) return `${s}s`;
  const minutes = Math.round(s / 60);
  if (minutes < 60) return `${minutes}m`;
  const hours = Math.round(minutes / 60);
  return `${hours}h`;
}

function fmtRate(value: number | null | undefined): string {
  if (value == null) return "—";
  return `${Number(value.toFixed(1))}/m`;
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

// Worst-color summary for the collapsed header dot. Severity order matches
// the var() palette: --negative > --warning > --positive. UNKNOWN states
// are mapped to --warning by their producers, which is the behaviour we
// want here too.
function worstStatus(statuses: { color: string }[]): {
  label: "OK" | "WARN" | "ALERT";
  color: string;
} {
  const colors = statuses.map((s) => s.color);
  if (colors.includes("var(--negative)"))
    return { label: "ALERT", color: "var(--negative)" };
  if (colors.includes("var(--warning)"))
    return { label: "WARN", color: "var(--warning)" };
  return { label: "OK", color: "var(--positive)" };
}

function readStoredCollapsed(): boolean {
  if (typeof window === "undefined") return true;
  try {
    const stored = window.localStorage?.getItem(COLLAPSED_STORAGE_KEY);
    if (stored == null) return true;
    return stored === "1";
  } catch {
    return true;
  }
}

function writeStoredCollapsed(value: boolean): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage?.setItem(COLLAPSED_STORAGE_KEY, value ? "1" : "0");
  } catch {
    // Quota exceeded / disabled storage — fall through and keep in-memory only.
  }
}

export function HealthPanel() {
  const [h, setH] = useState<Health | null>(null);
  const [source, setSource] = useState<ProviderSource>("uw");
  // Always start collapsed on server + first client render to avoid a
  // hydration mismatch; the real localStorage value is read in an effect.
  const [collapsed, setCollapsed] = useState<boolean>(true);

  useEffect(() => {
    // Syncing with localStorage requires a post-mount read; a lazy useState
    // initializer would still see SSR's undefined window and skip hydration.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setCollapsed(readStoredCollapsed());
  }, []);

  useEffect(() => {
    let cancelled = false;
    const fetchOnce = async () => {
      try {
        const r = await api.health(source, {
          recordMinCoverage: RECORD_MIN_COVERAGE,
          recordWindowHours: RECORD_WINDOW_HOURS,
        });
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
  const spotRefreshStatus = heartbeatStatus(
    h?.spot_refresh_heartbeat_lag_seconds,
    SPOT_REFRESH_HEALTHY_LAG_S,
  );
  const workerRows = h?.workers ?? [];
  const uwWorkers = workerRows.filter((worker) => worker.role === "uw");
  const massiveWorkers = workerRows.filter(
    (worker) => worker.role === "massive",
  );
  const recordsStatus = recordHealthStatus(h?.record_health_ok);
  const summary = worstStatus(
    workerRows.length > 0
      ? [
          apiStatus,
          schedulerStatus,
          workerGroupStatus(uwWorkers),
          workerGroupStatus(massiveWorkers),
          recordsStatus,
        ]
      : [
          apiStatus,
          schedulerStatus,
          rescanStatus,
          spotRefreshStatus,
          recordsStatus,
        ],
  );

  const toggle = () => {
    setCollapsed((prev) => {
      const next = !prev;
      writeStoredCollapsed(next);
      return next;
    });
  };

  return (
    <div style={{ borderTop: "1px solid var(--border-dim)" }}>
      <button
        type="button"
        onClick={toggle}
        aria-expanded={!collapsed}
        aria-controls="health-panel-body"
        title={`Status: ${summary.label}. Click to ${collapsed ? "expand" : "collapse"}.`}
        style={{
          width: "100%",
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          gap: 8,
          padding: "10px 16px",
          background: "transparent",
          border: "none",
          color: "var(--text-secondary)",
          cursor: "pointer",
          fontFamily: "var(--font-mono)",
          fontSize: 11,
          letterSpacing: 1.5,
          textTransform: "uppercase",
        }}
      >
        <span style={statusStyle}>
          <span
            style={{
              width: 8,
              height: 8,
              background: summary.color,
              display: "inline-block",
            }}
          />
          <span style={{ color: "var(--text-muted)" }}>Status</span>
          <span style={valStyle}>{summary.label}</span>
        </span>
        <span aria-hidden="true">{collapsed ? "▸" : "▾"}</span>
      </button>
      {!collapsed && (
        <div id="health-panel-body" style={{ padding: "0 16px 12px 16px" }}>
          <StatusRow label="API" status={apiStatus} />
          <StatusRow label="Scheduler" status={schedulerStatus} />
          {workerRows.length > 0 ? (
            <>
              <StatusRow
                label="UW Workers"
                status={workerGroupStatus(uwWorkers)}
              />
              <StatusRow
                label="Massive Workers"
                status={workerGroupStatus(massiveWorkers)}
              />
            </>
          ) : (
            <>
              <StatusRow label="UW Worker" status={rescanStatus} />
              <StatusRow label="Massive Worker" status={spotRefreshStatus} />
            </>
          )}
          <StatusRow label="Query Coverage" status={recordsStatus} />
          <div style={rowStyle}>
            <span style={labelStyle}>Last spot</span>
            <span
              style={valStyle}
              title={`Quote ${fmtDateTimeWithZone(h?.latest_spot_quote_at)} / fetched ${fmtDateTimeWithZone(h?.latest_spot_quote_fetched_at)}`}
            >
              {fmtDuration(h?.spot_quote_lag_seconds)}
            </span>
          </div>
          <div style={rowStyle}>
            <span style={labelStyle}>Last Scan</span>
            <span
              style={valStyle}
              title={fmtDateTimeWithZone(h?.last_full_scan_at)}
            >
              {fmtSidebarDateTime(h?.last_full_scan_at)}
            </span>
          </div>
          <div style={rowStyle}>
            <span style={labelStyle}>Source</span>
            <select
              aria-label="Source"
              value={source}
              onChange={(event) =>
                setSource(event.target.value as ProviderSource)
              }
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
            <span style={labelStyle}>Latency p95</span>
            <span style={valStyle}>{dash(h?.latency_p95_ms, "ms")}</span>
          </div>
          <div style={rowStyle}>
            <span style={labelStyle}>Req avg/min</span>
            <span style={valStyle}>{fmtRate(h?.requests_per_minute)}</span>
          </div>
          <div style={rowStyle}>
            <span style={labelStyle}>429</span>
            <span style={valStyle}>{dash(h?.http_429)}</span>
          </div>
          <div style={rowStyle}>
            <span style={labelStyle}>Scan avg</span>
            <span style={valStyle}>
              {fmtDuration(h?.avg_scan_duration_seconds)}
            </span>
          </div>
          <div style={rowStyle}>
            <span style={labelStyle}>Queue avg/min</span>
            <span style={valStyle}>
              {fmtRate(h?.queue_drain_rate_per_minute)}
            </span>
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
      )}
    </div>
  );
}
