"use client";
import { useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";
import { fmtDateTimeWithZone } from "@/lib/formatters";

import { BenchmarkView } from "./healthPanel/BenchmarkView";
import {
  type BenchmarkCurrent,
  type Health,
  type PanelView,
  type ProviderSource,
  HEALTH_FAILURE_LIMIT,
  HEALTH_FETCH_TIMEOUT_MS,
  HEALTH_TIME_ZONE,
  RECORD_MIN_COVERAGE,
  RECORD_WINDOW_HOURS,
  WORKER_HEARTBEAT_HEALTHY_LAG_S,
  dash,
  fmtDuration,
  fmtRate,
  fmtSidebarDateTime,
  heartbeatStatus,
  readStoredCollapsed,
  recordHealthStatus,
  workerGroupStatus,
  worstStatus,
  writeStoredCollapsed,
} from "./healthPanel/status";
import {
  labelStyle,
  panelButtonStyle,
  rowStyle,
  sourceSelectStyle,
  statusStyle,
  valStyle,
} from "./healthPanel/styles";
import { StatusRow } from "./healthPanel/StatusRow";

export function HealthPanel() {
  const [h, setH] = useState<Health | null>(null);
  const [source, setSource] = useState<ProviderSource>("uw");
  const [panelView, setPanelView] = useState<PanelView>("status");
  const [benchmark, setBenchmark] = useState<BenchmarkCurrent | null>(null);
  const [benchmarkError, setBenchmarkError] = useState(false);
  // Always start collapsed on server + first client render to avoid a
  // hydration mismatch; the real localStorage value is read in an effect.
  const [collapsed, setCollapsed] = useState<boolean>(true);

  useEffect(() => {
    // Syncing with localStorage requires a post-mount read; a lazy useState
    // initializer would still see SSR's undefined window and skip hydration.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setCollapsed(readStoredCollapsed());
  }, []);

  // A single slow/failed poll must NOT blank the whole panel to OFFLINE —
  // the record-health query can occasionally exceed the timeout even when the
  // API is fine. Keep the last-good snapshot until FAILURE_LIMIT consecutive
  // misses (a genuine outage), and cap each poll at HEALTH_FETCH_TIMEOUT_MS so
  // a real outage is detected promptly instead of hanging. Polls are SERIALIZED
  // (schedule the next only after the current settles) rather than a fixed
  // interval: with an 8s timeout under a 5s interval, requests would overlap and
  // an older timed-out poll could bump the failure counter after a newer poll
  // already succeeded — muddying the "consecutive" count and re-introducing a
  // false OFFLINE while the API is healthy.
  const failuresRef = useRef(0);
  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    failuresRef.current = 0;
    const scheduleNext = () => {
      if (!cancelled) timer = setTimeout(runPoll, 5000);
    };
    const runPoll = async () => {
      try {
        const r = await api.health(
          source,
          {
            recordMinCoverage: RECORD_MIN_COVERAGE,
            recordWindowHours: RECORD_WINDOW_HOURS,
          },
          { signal: AbortSignal.timeout(HEALTH_FETCH_TIMEOUT_MS) },
        );
        if (cancelled) return;
        failuresRef.current = 0;
        setH(r);
      } catch {
        if (cancelled) return;
        failuresRef.current += 1;
        if (failuresRef.current >= HEALTH_FAILURE_LIMIT) setH(null);
        // else: keep the last-good snapshot — this was a transient slow poll.
      } finally {
        if (!cancelled) scheduleNext();
      }
    };
    runPoll();
    return () => {
      cancelled = true;
      if (timer !== undefined) clearTimeout(timer);
    };
  }, [source]);

  useEffect(() => {
    if (collapsed || panelView !== "benchmark") return;
    let cancelled = false;
    api
      .healthBenchmarkCurrent()
      .then((response) => {
        if (!cancelled) {
          setBenchmark(response);
          setBenchmarkError(false);
        }
      })
      .catch(() => {
        if (!cancelled) {
          setBenchmark(null);
          setBenchmarkError(true);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [collapsed, panelView]);

  const apiStatus =
    h == null
      ? { label: "OFFLINE", color: "var(--negative)" }
      : { label: "ONLINE", color: "var(--positive)" };
  const schedulerStatus = heartbeatStatus(
    h?.scheduler_heartbeat_lag_seconds,
    WORKER_HEARTBEAT_HEALTHY_LAG_S,
  );
  const rescanStatus = heartbeatStatus(h?.rescan_heartbeat_lag_seconds);
  const workerRows = h?.workers ?? [];
  const uwWorkers = workerRows.filter((worker) => worker.role === "uw");
  const massiveWorkers = workerRows.filter(
    (worker) => worker.role === "massive",
  );
  const aiWorkers = workerRows.filter((worker) => worker.role === "ai");
  const recordsStatus = recordHealthStatus(h?.record_health_ok);
  // Massive.com WS consumer: the only safety signal under the no-fallback
  // design. If this dot is red and the market is open, prices ARE stale.
  const wsConsumer = h?.ws_consumer ?? null;
  const wsStatus: { label: string; color: string } = (() => {
    if (!wsConsumer) return { label: "UNKNOWN", color: "var(--warning)" };
    if (wsConsumer.healthy)
      return { label: "ONLINE", color: "var(--positive)" };
    return {
      label: (wsConsumer.reason ?? "STALE").toUpperCase().slice(0, 12),
      color: "var(--negative)",
    };
  })();
  const summary = worstStatus(
    workerRows.length > 0
      ? [
          apiStatus,
          schedulerStatus,
          workerGroupStatus(uwWorkers),
          workerGroupStatus(massiveWorkers),
          // Only include AI workers in the worst-status summary when they
          // exist — otherwise workerGroupStatus([]) returns "UNKNOWN" and
          // would tip the collapsed dot to warning unnecessarily.
          ...(aiWorkers.length > 0 ? [workerGroupStatus(aiWorkers)] : []),
          recordsStatus,
          wsStatus,
        ]
      : [apiStatus, schedulerStatus, rescanStatus, recordsStatus, wsStatus],
  );

  const toggle = () => {
    setCollapsed((prev) => {
      const next = !prev;
      writeStoredCollapsed(next);
      return next;
    });
  };
  const showBenchmark = () => {
    setBenchmarkError(false);
    setPanelView("benchmark");
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
          {h?.version && (
            <span
              style={{
                color: "var(--text-muted)",
                textTransform: "none",
                letterSpacing: 0,
              }}
              title={`Deployed backend version v${h.version}`}
            >
              v{h.version}
            </span>
          )}
        </span>
        <span aria-hidden="true">{collapsed ? "▸" : "▾"}</span>
      </button>
      {!collapsed && (
        <div id="health-panel-body" style={{ padding: "0 16px 12px 16px" }}>
          {panelView === "benchmark" ? (
            <BenchmarkView
              benchmark={benchmark}
              loading={benchmark == null && !benchmarkError}
              error={benchmarkError}
              onBack={() => setPanelView("status")}
            />
          ) : (
            <>
              <div
                style={{
                  ...rowStyle,
                  alignItems: "center",
                  paddingBottom: 8,
                }}
              >
                <span style={{ color: "var(--text-secondary)" }}>Health</span>
                <button
                  type="button"
                  onClick={showBenchmark}
                  style={panelButtonStyle}
                >
                  Benchmark
                </button>
              </div>
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
                  {aiWorkers.length > 0 && (
                    <StatusRow
                      label="AI Workers"
                      status={workerGroupStatus(aiWorkers)}
                    />
                  )}
                </>
              ) : (
                <>
                  {/* No Massive Worker row in this fallback: its only source
                      was the spot_refresh heartbeat, retired in Phase 7. With
                      zero worker rows there is nothing left to report, and a
                      permanently-red row is worse than an absent one. */}
                  <StatusRow label="UW Worker" status={rescanStatus} />
                </>
              )}
              <StatusRow label="Query Coverage" status={recordsStatus} />
              <div style={rowStyle}>
                <span style={labelStyle}>Last spot</span>
                <span
                  style={valStyle}
                  title={`Quote ${fmtDateTimeWithZone(h?.latest_spot_quote_at, { timeZone: HEALTH_TIME_ZONE })} / fetched ${fmtDateTimeWithZone(h?.latest_spot_quote_fetched_at, { timeZone: HEALTH_TIME_ZONE })}`}
                >
                  {fmtDuration(h?.spot_quote_lag_seconds)}
                </span>
              </div>
              <StatusRow label="WS Consumer" status={wsStatus} />
              {wsConsumer?.active_source && (
                <div style={rowStyle}>
                  <span style={labelStyle}>WS feed</span>
                  <span
                    style={{
                      ...valStyle,
                      color:
                        wsConsumer.active_source === "xenon_ws"
                          ? "var(--positive)"
                          : "var(--warning)",
                    }}
                    title={
                      wsConsumer.active_source === "xenon_ws"
                        ? "xenon IB realtime (primary)"
                        : "massive.com WS (fallback)"
                    }
                  >
                    {wsConsumer.active_source === "xenon_ws"
                      ? "XENON"
                      : "MASSIVE"}
                  </span>
                </div>
              )}
              {wsConsumer && (
                <div style={rowStyle}>
                  <span style={labelStyle}>WS tick age</span>
                  <span style={valStyle}>
                    {fmtDuration(wsConsumer.last_tick_age_seconds ?? null)}
                  </span>
                </div>
              )}
              {wsConsumer && (
                <div style={rowStyle}>
                  <span style={labelStyle}>WS received</span>
                  <span style={valStyle}>
                    {wsConsumer.ticks_received.toLocaleString()}
                  </span>
                </div>
              )}
              <div style={rowStyle}>
                <span style={labelStyle}>Last Scan</span>
                <span
                  style={valStyle}
                  title={fmtDateTimeWithZone(h?.last_full_scan_at, {
                    timeZone: HEALTH_TIME_ZONE,
                  })}
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
            </>
          )}
        </div>
      )}
    </div>
  );
}
