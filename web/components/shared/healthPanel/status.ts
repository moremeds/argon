import { fmtDateTimeWithZone } from "@/lib/formatters";
import type { components } from "@/lib/types";

export type Health = components["schemas"]["HealthResponse"];
export type BenchmarkCurrent =
  components["schemas"]["BenchmarkCurrentResponse"];
export type WorkerHealth = NonNullable<Health["workers"]>[number];
export type ProviderSource = "uw" | "massive";
export type PanelView = "status" | "benchmark";

export const HEALTH_FETCH_TIMEOUT_MS = 8000;
export const HEALTH_FAILURE_LIMIT = 3;
const HEARTBEAT_HEALTHY_LAG_S = 5;
// The per-worker `worker_heartbeat` job beats every 15 s (was 1 s), so the
// scheduler dot and the uw/ai worker rows allow 3 intervals. rescan_tick still
// beats every second and keeps the 5 s threshold.
export const WORKER_HEARTBEAT_HEALTHY_LAG_S = 45;
// Massive workers beat on the daily OHLC cadence, not the 5s worker tick, so
// they get their own generous threshold. (Was SPOT_REFRESH_HEALTHY_LAG_S, back
// when the retired spot_refresh job set the cadence.)
const MASSIVE_HEALTHY_LAG_S = 660;
export const RECORD_WINDOW_HOURS = 8;
export const RECORD_MIN_COVERAGE = 0.9;
const COLLAPSED_STORAGE_KEY = "uw_health_collapsed";
export const HEALTH_TIME_ZONE = "Asia/Hong_Kong";

export function dash(
  v: number | string | null | undefined,
  suffix = "",
): string {
  if (v == null || v === "") return "—";
  return `${v}${suffix}`;
}

export function fmtSidebarDateTime(iso: string | null | undefined): string {
  const full = fmtDateTimeWithZone(iso, { timeZone: HEALTH_TIME_ZONE });
  if (full === "—") return full;
  const match = full.match(
    /^\d{4}\/(\d{2})\/(\d{2}) (\d{2}):(\d{2}):\d{2} (.+)$/,
  );
  if (!match) return full;
  const [, month, day, hour, minute, zone] = match;
  return `${month}/${day} ${hour}:${minute} ${zone}`;
}

export function heartbeatStatus(
  lagSeconds: number | null | undefined,
  healthyLagSeconds = HEARTBEAT_HEALTHY_LAG_S,
): { label: "ONLINE" | "STALE" | "UNKNOWN"; color: string } {
  if (lagSeconds == null) return { label: "UNKNOWN", color: "var(--warning)" };
  if (lagSeconds <= healthyLagSeconds) {
    return { label: "ONLINE", color: "var(--positive)" };
  }
  return { label: "STALE", color: "var(--warning)" };
}

export function recordHealthStatus(ok: boolean | null | undefined): {
  label: "OK" | "ALERT" | "UNKNOWN";
  color: string;
} {
  if (ok == null) return { label: "UNKNOWN", color: "var(--warning)" };
  if (ok) return { label: "OK", color: "var(--positive)" };
  return { label: "ALERT", color: "var(--negative)" };
}

export function workerGroupStatus(workers: WorkerHealth[]): {
  label: string;
  color: string;
} {
  if (workers.length === 0)
    return { label: "UNKNOWN", color: "var(--warning)" };
  const online = workers.filter((worker) => {
    const healthyLag =
      worker.role === "massive"
        ? MASSIVE_HEALTHY_LAG_S
        : WORKER_HEARTBEAT_HEALTHY_LAG_S;
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

export function fmtDuration(seconds: number | null | undefined): string {
  if (seconds == null) return "—";
  const s = Math.max(0, Math.round(seconds));
  if (s < 60) return `${s}s`;
  const minutes = Math.round(s / 60);
  if (minutes < 60) return `${minutes}m`;
  const hours = Math.round(minutes / 60);
  return `${hours}h`;
}

export function fmtRate(value: number | null | undefined): string {
  if (value == null) return "—";
  return `${Number(value.toFixed(1))}/m`;
}

export function benchmarkStatusColor(
  status: BenchmarkCurrent["status"],
): string {
  if (status === "OK") return "var(--positive)";
  if (status === "DEGRADED") return "var(--warning)";
  return "var(--negative)";
}

// Worst-color summary for the collapsed header dot. Severity order matches
// the var() palette: --negative > --warning > --positive. UNKNOWN states
// are mapped to --warning by their producers, which is the behaviour we
// want here too.
export function worstStatus(statuses: { color: string }[]): {
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

export function readStoredCollapsed(): boolean {
  if (typeof window === "undefined") return true;
  try {
    const stored = window.localStorage?.getItem(COLLAPSED_STORAGE_KEY);
    if (stored == null) return true;
    return stored === "1";
  } catch {
    return true;
  }
}

export function writeStoredCollapsed(value: boolean): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage?.setItem(COLLAPSED_STORAGE_KEY, value ? "1" : "0");
  } catch {
    // Quota exceeded / disabled storage — fall through and keep in-memory only.
  }
}
