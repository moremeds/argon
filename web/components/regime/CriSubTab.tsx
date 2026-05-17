"use client";

import { useMemo, useState } from "react";
import { AlertTriangle, Check, Shield, X, Zap } from "lucide-react";

import CriHistoryChart, {
  type ChartSeries,
  type CriHistoryEntry,
} from "./CriHistoryChart";
import InfoTooltip from "./InfoTooltip";
import {
  DayChange,
  LiveBadge,
  PointChange,
  RegimeStrip,
  RegimeStripCell,
} from "./RegimeStrip";
import { type CriBlock, type CriResponse, useCri } from "@/lib/regime/useCri";

type CriLevel = "LOW" | "ELEVATED" | "HIGH" | "CRITICAL";

const COMPONENT_TOOLTIPS: Record<string, string> = {
  VIX: "CBOE Volatility Index — 30-day implied vol of SPX. Score rises as VIX exceeds 20 (elevated) and 30 (high).",
  VVIX: "Vol-of-VIX — measures expected volatility of VIX itself. Score rises with absolute level and VVIX/VIX ratio >5.",
  CORRELATION:
    "Cboe 1-Month Implied Correlation Index (COR1M). High COR1M (>60) means large-cap S&P names are expected to move together.",
  MOMENTUM:
    "SPX distance below 100-day MA combined with VIX 5-day rate of change. Captures trend stress + vol acceleration.",
};

const SECTION_TOOLTIPS: Record<string, string> = {
  "CRI COMPONENTS":
    "Crash Risk Index broken into 4 sub-scores (0-25 each, 100 total). VIX/VVIX measure implied vol stress. Correlation tracks COR1M herding. Momentum captures SPX trend breakdown.",
  "CRASH TRIGGER CONDITIONS":
    "Three simultaneous conditions that signal a potential crash regime: SPX below 100d MA, realized vol > 25%, and COR1M > 60. All three must fire.",
  "20-SESSION HISTORY":
    "Left chart tracks VIX and VVIX. Right chart compares realized volatility with COR1M over the same window. Latest point is the most recent session.",
};

function levelColor(level: CriLevel): string {
  switch (level) {
    case "LOW":
      return "var(--positive)";
    case "ELEVATED":
      return "var(--warning)";
    case "HIGH":
      return "var(--negative)";
    case "CRITICAL":
      return "var(--negative)";
  }
}

function fmt(v: number | null | undefined, decimals = 2): string {
  if (v == null || !Number.isFinite(v)) return "---";
  return v.toFixed(decimals);
}

function fmtPct(v: number | null | undefined, decimals = 2): string {
  if (v == null || !Number.isFinite(v)) return "---";
  return `${v >= 0 ? "+" : ""}${v.toFixed(decimals)}%`;
}

function fmtSigned(v: number | null | undefined, decimals = 2): string {
  if (v == null || !Number.isFinite(v)) return "---";
  return `${v >= 0 ? "+" : ""}${v.toFixed(decimals)}`;
}

function ComponentBar({
  label,
  score,
  live,
}: {
  label: string;
  score: number;
  live: boolean;
}) {
  const pct = (score / 25) * 100;
  const barColor =
    score < 8
      ? "var(--positive)"
      : score > 16
        ? "var(--negative)"
        : "var(--warning)";
  const tooltip = COMPONENT_TOOLTIPS[label];
  return (
    <div className="regime-component-bar">
      <div className="regime-component-label">
        <span style={{ flex: 1 }}>{label}</span>
        {tooltip && <InfoTooltip text={tooltip} />}
        <LiveBadge live={live} />
      </div>
      <div className="regime-bar-track">
        <div
          className="regime-bar-fill"
          style={{ width: `${pct}%`, background: barColor }}
        />
      </div>
      <div className="regime-component-score">{score.toFixed(1)}/25</div>
    </div>
  );
}

function TriggerRow({
  label,
  met,
  value,
  live,
}: {
  label: string;
  met: boolean;
  value: string;
  live: boolean;
}) {
  return (
    <div className="regime-trigger-row">
      <div className="regime-trigger-icon">
        {met ? (
          <Check size={14} color="var(--positive)" />
        ) : (
          <X size={14} color="var(--negative)" />
        )}
      </div>
      <div className="regime-trigger-label">{label}</div>
      <div className="regime-trigger-value">{value}</div>
      <LiveBadge live={live} />
    </div>
  );
}

// Pull prior-day values for DayChange from the history array (snapshot stored
// the trailing 20 sessions including today). Today's close lives in the snapshot
// scalars; "previous close" is history[history.length - 2][key].
function prevClose(
  history: CriHistoryEntry[] | undefined,
  key: keyof CriHistoryEntry,
): number | null {
  if (!history || history.length < 2) return null;
  const v = history[history.length - 2][key];
  return typeof v === "number" && Number.isFinite(v) ? v : null;
}

const VIX_VVIX_LEFT: ChartSeries = {
  key: "vix",
  label: "VIX",
  color: "var(--signal-core, #05AD98)",
  axis: "left",
  format: (v) => v.toFixed(1),
};
const VIX_VVIX_RIGHT: ChartSeries = {
  key: "vvix",
  label: "VVIX",
  color: "var(--extreme, #8B5CF6)",
  axis: "right",
  format: (v) => v.toFixed(0),
};
const RVOL_LEFT: ChartSeries = {
  key: "realized_vol",
  label: "RVOL",
  color: "var(--warning, #F5A623)",
  axis: "left",
  format: (v) => `${v.toFixed(1)}%`,
};
const COR_RIGHT: ChartSeries = {
  key: "cor1m",
  label: "COR1M",
  color: "var(--dislocation, #D946A8)",
  axis: "right",
  format: (v) => v.toFixed(1),
};

type CriTableSortCol =
  | "date"
  | "vix"
  | "vvix"
  | "spy"
  | "cor1m"
  | "realized_vol"
  | "spx_vs_ma_pct"
  | "vix_5d_roc";
type SortDir = "asc" | "desc";

function sortIndicator(
  col: CriTableSortCol,
  active: CriTableSortCol | null,
  dir: SortDir,
): string {
  if (active !== col) return "";
  return dir === "asc" ? " ▲" : " ▼";
}

function fmtNum(v: number | null | undefined, dec = 2): string {
  if (v == null || !Number.isFinite(v)) return "—";
  return v.toFixed(dec);
}

function fmtPctCell(v: number | null | undefined, dec = 2): string {
  if (v == null || !Number.isFinite(v)) return "—";
  return `${v >= 0 ? "+" : ""}${v.toFixed(dec)}%`;
}

function CriHistoryTable({ history }: { history: CriHistoryEntry[] }) {
  const [sortCol, setSortCol] = useState<CriTableSortCol | null>(null);
  const [sortDir, setSortDir] = useState<SortDir>("desc");
  const [expanded, setExpanded] = useState(true);

  function onSort(col: CriTableSortCol) {
    if (sortCol === col) {
      if (sortDir === "desc") setSortDir("asc");
      else {
        setSortCol(null);
        setSortDir("desc");
      }
    } else {
      setSortCol(col);
      setSortDir("desc");
    }
  }

  const sorted = useMemo(() => {
    if (!sortCol) return [...history].reverse(); // newest first by default
    return [...history].sort((a, b) => {
      const av =
        sortCol === "date"
          ? a.date
          : ((a[sortCol] as number | null | undefined) ?? -Infinity);
      const bv =
        sortCol === "date"
          ? b.date
          : ((b[sortCol] as number | null | undefined) ?? -Infinity);
      if (av < bv) return sortDir === "asc" ? -1 : 1;
      if (av > bv) return sortDir === "asc" ? 1 : -1;
      return 0;
    });
  }, [history, sortCol, sortDir]);

  if (!history.length) return null;

  const cols: { key: CriTableSortCol; label: string; align: string }[] = [
    { key: "date", label: "Date", align: "left" },
    { key: "vix", label: "VIX", align: "right" },
    { key: "vvix", label: "VVIX", align: "right" },
    { key: "spy", label: "SPY", align: "right" },
    { key: "cor1m", label: "COR1M", align: "right" },
    { key: "realized_vol", label: "RVOL", align: "right" },
    { key: "spx_vs_ma_pct", label: "vs 100d MA", align: "right" },
    { key: "vix_5d_roc", label: "VIX 5d RoC", align: "right" },
  ];

  return (
    <div
      className="gex-history-section"
      data-testid="cri-history-table-section"
    >
      <button
        className="gex-history-toggle"
        onClick={() => setExpanded(!expanded)}
        data-testid="cri-history-table-toggle"
      >
        History ({history.length} sessions) {expanded ? "▲" : "▼"}
      </button>
      {expanded && (
        <div className="gex-history-table-wrap">
          <table className="gex-history-table" data-testid="cri-history-table">
            <thead>
              <tr>
                {cols.map((c) => (
                  <th
                    key={c.key}
                    className={`text-${c.align}`}
                    onClick={() => onSort(c.key)}
                    style={{ cursor: "pointer", userSelect: "none" }}
                  >
                    {c.label}
                    {sortIndicator(c.key, sortCol, sortDir)}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {sorted.map((row) => (
                <tr key={row.date}>
                  <td>{row.date}</td>
                  <td className="text-right">{fmtNum(row.vix, 2)}</td>
                  <td className="text-right">{fmtNum(row.vvix, 1)}</td>
                  <td className="text-right">
                    {row.spy != null ? `$${fmtNum(row.spy, 2)}` : "—"}
                  </td>
                  <td className="text-right">{fmtNum(row.cor1m, 2)}</td>
                  <td className="text-right">
                    {row.realized_vol != null
                      ? `${fmtNum(row.realized_vol, 1)}%`
                      : "—"}
                  </td>
                  <td
                    className="text-right"
                    style={{
                      color:
                        row.spx_vs_ma_pct == null
                          ? undefined
                          : row.spx_vs_ma_pct >= 0
                            ? "var(--positive)"
                            : "var(--negative)",
                    }}
                  >
                    {fmtPctCell(row.spx_vs_ma_pct, 2)}
                  </td>
                  <td
                    className="text-right"
                    style={{
                      color:
                        row.vix_5d_roc == null
                          ? undefined
                          : row.vix_5d_roc >= 0
                            ? "var(--negative)"
                            : "var(--positive)",
                    }}
                  >
                    {fmtPctCell(row.vix_5d_roc, 1)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

export function CriSubTabView({ data }: { data: CriResponse | null }) {
  // Empty/loading state — mirrors xenon's "no CRI data" shield empty.
  if (!data || data.status === "empty") {
    return (
      <div className="regime-empty" data-testid="cri-empty-state">
        <Shield size={32} strokeWidth={1} />
        <p>No CRI data available. Click Sync Now to run a scan.</p>
      </div>
    );
  }

  const cri: CriBlock = data.cri ?? {
    score: 0,
    level: "LOW",
    components: { vix: 0, vvix: 0, correlation: 0, momentum: 0 },
  };
  const level = cri.level as CriLevel;
  const color = levelColor(level);
  const components = cri.components ?? {
    vix: 0,
    vvix: 0,
    correlation: 0,
    momentum: 0,
  };

  // We don't have IB live ticks in this project — all values are end-of-day.
  // Drive the strip with the snapshot's scalars + history-derived prior closes.
  const history = (data.history ?? []) as CriHistoryEntry[];
  const vix = data.vix ?? null;
  const vvix = data.vvix ?? null;
  const spy = data.spy ?? null;
  const cor1m = data.cor1m ?? null;
  const realizedVol = data.realized_vol ?? null;

  const vixClose = prevClose(history, "vix");
  const vvixClose = prevClose(history, "vvix");
  const spyClose = prevClose(history, "spy");
  const cor1mPrevClose =
    data.cor1m_previous_close ?? prevClose(history, "cor1m");

  const corr5dChange = data.cor1m_5d_change ?? null;
  const vvixVixRatio =
    data.vvix_vix_ratio ?? (vix && vix > 0 && vvix != null ? vvix / vix : null);
  const spxDistPct = data.spx_distance_pct ?? null;
  const ma = data.spx_100d_ma ?? null;
  const trigger = data.crash_trigger;
  const triggered = trigger?.triggered ?? trigger?.fired ?? false;
  const correlationTriggerMet =
    trigger?.conditions?.cor1m_gt_60 ?? (cor1m != null && cor1m > 60);
  const spxBelowMa = trigger?.conditions?.spx_below_100d_ma ?? false;
  const rvolTriggerMet = trigger?.conditions?.realized_vol_gt_25 ?? false;

  // Page is end-of-day in this project — never "live".
  const live = false;
  const lastSync = data.scan_time || null;

  // History payload is the 20-session window (oldest → newest).
  const liveValues = useMemo(() => ({}), []);

  return (
    <div className="regime-panel" data-testid="cri-subtab">
      {/* ── Row 1: Hero ───────────────────── */}
      <div className="regime-hero">
        <div className="regime-hero-score" style={{ color }}>
          <span data-testid="cri-score">{cri.score.toFixed(0)}</span>
          <span className="regime-hero-max">/100</span>
        </div>
        <div className="regime-hero-meta">
          <span
            className="regime-level-badge"
            style={{
              background: color,
              color: level === "LOW" ? "#000" : "#fff",
            }}
            data-testid="cri-level"
          >
            {level}
          </span>
          <span
            className="regime-live-dot"
            style={{ background: "var(--text-muted)" }}
          />
          <span className="regime-hero-label">CACHED</span>
          {lastSync && (
            <span className="regime-hero-timestamp">
              Last scan: {new Date(lastSync).toLocaleTimeString()}
            </span>
          )}
        </div>
        <div className="regime-hero-bar">
          <div
            className="regime-hero-bar-fill"
            style={{ width: `${cri.score}%`, background: color }}
          />
        </div>
        <div className="regime-hero-scale">
          <span>LOW</span>
          <span>ELEVATED</span>
          <span>HIGH</span>
          <span>CRITICAL</span>
        </div>
      </div>

      {/* ── Row 2: Live ticker strip (DAILY badges in our project) ── */}
      <RegimeStrip>
        <RegimeStripCell
          testId="strip-vix"
          label={
            <>
              VIX <LiveBadge live={live} />
            </>
          }
          value={fmt(vix)}
          change={<DayChange last={vix} close={vixClose} />}
          sub={<>5d RoC: {fmtPct(data.vix_5d_roc, 1)}</>}
        />
        <RegimeStripCell
          testId="strip-vvix"
          label={
            <>
              VVIX <LiveBadge live={live} />
            </>
          }
          value={fmt(vvix)}
          change={<DayChange last={vvix} close={vvixClose} />}
          sub={<>VVIX/VIX: {fmt(vvixVixRatio)}</>}
        />
        <RegimeStripCell
          testId="strip-spy"
          label={
            <>
              SPY <LiveBadge live={live} />
            </>
          }
          value={`$${fmt(spy)}`}
          change={<DayChange last={spy} close={spyClose} prefix="$" />}
          sub={<>vs 100d MA: {fmtPct(spxDistPct)}</>}
        />
        <RegimeStripCell
          testId="strip-rvol"
          label={
            <>
              <span className="regime-strip-label-text-full">REALIZED VOL</span>
              <span className="regime-strip-label-text-short">RVOL</span>
              <LiveBadge live={live} />
            </>
          }
          value={realizedVol != null ? `${fmt(realizedVol)}%` : "---"}
          change={<PointChange change={null} suffix="%" label="intraday" />}
          sub={<>20d annualized</>}
        />
        <RegimeStripCell
          testId="strip-cor1m"
          label={
            <>
              COR1M <LiveBadge live={live} />
            </>
          }
          value={fmt(cor1m, 2)}
          change={<DayChange last={cor1m} close={cor1mPrevClose} />}
          sub={
            <>{`5d chg: ${corr5dChange != null ? `${fmtSigned(corr5dChange)} pts` : "---"}`}</>
          }
        />
      </RegimeStrip>

      {/* ── Row 3+4: Components + Crash trigger ── */}
      <div className="regime-detail-grid">
        <div className="regime-components">
          <div className="regime-panel-title">
            <Zap size={12} />
            CRI COMPONENTS
            <InfoTooltip text={SECTION_TOOLTIPS["CRI COMPONENTS"]} />
          </div>
          <ComponentBar label="VIX" score={components.vix} live={live} />
          <ComponentBar label="VVIX" score={components.vvix} live={live} />
          <ComponentBar
            label="CORRELATION"
            score={components.correlation}
            live={live}
          />
          <ComponentBar
            label="MOMENTUM"
            score={components.momentum}
            live={live}
          />
        </div>
        <div className="regime-triggers">
          <div className="regime-panel-title">
            <AlertTriangle size={12} />
            CRASH TRIGGER CONDITIONS
            <InfoTooltip text={SECTION_TOOLTIPS["CRASH TRIGGER CONDITIONS"]} />
          </div>
          <div
            className={`regime-trigger-status ${triggered ? "regime-triggered" : ""}`}
            data-testid="crash-trigger-state"
          >
            {triggered ? "TRIGGERED" : "INACTIVE"}
          </div>
          <TriggerRow
            label="SPX < 100d MA"
            met={spxBelowMa}
            value={`${fmtPct(spxDistPct)} (MA: $${fmt(ma)})`}
            live={live}
          />
          <TriggerRow
            label="Realized Vol > 25%"
            met={rvolTriggerMet}
            value={realizedVol != null ? `${fmt(realizedVol)}%` : "---"}
            live={live}
          />
          <TriggerRow
            label="COR1M > 60"
            met={correlationTriggerMet}
            value={fmt(cor1m, 2)}
            live={live}
          />
        </div>
      </div>

      {/* ── Row 5: 20-Session History (two charts side-by-side) ── */}
      {history.length > 0 && (
        <>
          <div className="section-header" data-testid="regime-history-header">
            <div className="section-title" data-testid="regime-history-title">
              <span>20-SESSION HISTORY</span>
              <InfoTooltip text={SECTION_TOOLTIPS["20-SESSION HISTORY"]} />
            </div>
          </div>
          <div
            className="regime-history-grid"
            data-testid="regime-history-grid"
          >
            <div data-testid="regime-history-chart-vix-vvix">
              <CriHistoryChart
                history={history}
                series={[VIX_VVIX_LEFT, VIX_VVIX_RIGHT]}
                title="VIX / VVIX"
                liveValues={liveValues}
              />
            </div>
            <div data-testid="regime-history-chart-rvol-cor1m">
              <CriHistoryChart
                history={history}
                series={[RVOL_LEFT, COR_RIGHT]}
                title="REALIZED VOL / COR1M"
                liveValues={liveValues}
              />
            </div>
          </div>
          <CriHistoryTable history={history} />
        </>
      )}
    </div>
  );
}

export default function CriSubTab() {
  const { data } = useCri();
  return <CriSubTabView data={data} />;
}
