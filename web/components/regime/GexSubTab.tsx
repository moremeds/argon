"use client";

import { useMemo, useState } from "react";
import { Activity, TrendingUp, TrendingDown } from "lucide-react";
import {
  useGex,
  type GexData,
  type GexHistoryEntry,
  type GexLevel,
  type MqLevels,
  type SourceDelta,
  type SourceDeltaEntry,
} from "@/lib/regime/useGex";
import { MarketState } from "@/lib/regime/useMarketHours";
import InfoTooltip from "./InfoTooltip";
import GexProfileChart from "./GexProfileChart";
import { HistoryChart } from "./HistoryChart";
import { formatPercent } from "./primitives/format";
import { MetricCard, SourceBadge } from "./ui/MetricCard";

type GexSubTabProps = {
  marketState?: MarketState;
};

/* ─── Helpers ─────────────────────────────────────────── */

function fmtGex(v: number | null | undefined): string {
  if (v == null) return "---";
  const absVal = Math.abs(v);
  if (absVal >= 1_000_000)
    return `${v >= 0 ? "+" : ""}$${(v / 1_000_000).toFixed(1)}M`;
  if (absVal >= 1_000) return `${v >= 0 ? "+" : ""}$${(v / 1_000).toFixed(1)}K`;
  return `${v >= 0 ? "+" : ""}$${v.toFixed(0)}`;
}

function fmtPrice(v: number | null | undefined): string {
  if (v == null) return "---";
  return v.toLocaleString("en-US", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
}

function biasColor(direction: string): string {
  switch (direction) {
    case "BULL":
      return "var(--signal-core)";
    case "CAUTIOUS_BULL":
      return "var(--signal-core)";
    case "BEAR":
      return "var(--fault)";
    case "CAUTIOUS_BEAR":
      return "var(--fault)";
    default:
      return "var(--neutral)";
  }
}

function biasLabel(direction: string): string {
  return direction.replace("_", " ");
}

/* ─── Spot freshness pill ─────────────────────────────── */

/**
 * Render "LIVE", "Xm ago", or "Xh ago" based on age of `tape_time`.
 * Color: green ≤2m, warning ≤15m, muted-warm ≤60m, muted thereafter.
 * Returns null if tape_time is missing/invalid — caller renders nothing.
 *
 * Re-renders are driven by the GEX poll cycle (every N seconds); we don't
 * run a clock interval, which keeps this trivially pure.
 */
export function SpotFreshnessPill({
  tapeTime,
  nowMs,
}: {
  tapeTime: string | null | undefined;
  /** Injectable for tests and data-derived render anchors. */
  nowMs?: number;
}) {
  if (!tapeTime) return null;
  const t = Date.parse(tapeTime);
  if (Number.isNaN(t)) return null;
  if (nowMs == null) return null;
  const now = nowMs;
  const ageMin = Math.max(0, Math.floor((now - t) / 60000));

  let label: string;
  let color: string;
  let bg: string;
  if (ageMin <= 2) {
    label = "LIVE";
    color = "var(--signal-core)";
    bg = "rgba(15,110,86,0.18)";
  } else if (ageMin < 60) {
    label = `${ageMin}m ago`;
    color = ageMin <= 15 ? "var(--warning)" : "var(--text-secondary)";
    bg = ageMin <= 15 ? "rgba(245,166,35,0.15)" : "rgba(148,163,184,0.12)";
  } else if (ageMin < 60 * 24) {
    const hrs = Math.floor(ageMin / 60);
    label = `${hrs}h ago`;
    color = "var(--text-muted)";
    bg = "rgba(148,163,184,0.10)";
  } else {
    const days = Math.floor(ageMin / (60 * 24));
    label = `${days}d ago`;
    color = "var(--text-muted)";
    bg = "rgba(148,163,184,0.10)";
  }

  return (
    <span
      data-testid="spot-freshness-pill"
      style={{
        background: bg,
        color,
        fontSize: 9,
        fontWeight: 500,
        padding: "1px 5px",
        borderRadius: 2,
        letterSpacing: "0.06em",
      }}
      title={`Last tick at ${tapeTime}`}
    >
      {label}
    </span>
  );
}

/* ─── Level Card ──────────────────────────────────────── */

function LevelCard({
  label,
  level,
  labelColor,
}: {
  label: string;
  level: GexLevel;
  labelColor?: string;
}) {
  if (!level) {
    return (
      <div className="gex-level-card">
        <div className="gex-level-label" style={{ color: labelColor }}>
          {label}
        </div>
        <div className="gex-level-value">---</div>
      </div>
    );
  }
  return (
    <div className="gex-level-card">
      <div className="gex-level-label" style={{ color: labelColor }}>
        {label}
      </div>
      <div className="gex-level-value">{fmtPrice(level.strike)}</div>
      <div className="gex-level-sub">
        {formatPercent(level.distance_pct)} &mdash; {fmtGex(level.gamma)} per $1
      </div>
    </div>
  );
}

/* ─── Expected Range Bar ─────────────────────────────── */

function ExpectedRangeBar({ data }: { data: GexData }) {
  const { expected_range, levels, spot } = data;
  if (!expected_range.low || !expected_range.high) return null;

  const low = expected_range.low;
  const high = expected_range.high;
  const flip = levels.gex_flip?.strike;
  const magnet = levels.max_magnet?.strike;
  const accel = levels.max_accelerator?.strike;

  const allPoints = [low, high, spot];
  if (flip) allPoints.push(flip);
  if (magnet) allPoints.push(magnet);
  if (accel) allPoints.push(accel);
  const minVal = Math.min(...allPoints);
  const maxVal = Math.max(...allPoints);
  const range = maxVal - minVal || 1;
  const pct = (v: number) => ((v - minVal) / range) * 100;

  return (
    <div className="gex-range-container">
      <div className="gex-range-title">
        EXPECTED RANGE &mdash; {data.data_date}
      </div>
      <div className="gex-range-bar">
        <div
          className="gex-range-fill"
          style={{ left: `${pct(low)}%`, width: `${pct(high) - pct(low)}%` }}
        />
        {/* Markers */}
        {flip && (
          <div
            className="gex-range-marker"
            style={{ left: `${pct(flip)}%`, borderColor: "var(--warning)" }}
            title={`GEX FLIP: ${fmtPrice(flip)}`}
          />
        )}
        <div
          className="gex-range-marker"
          style={{ left: `${pct(spot)}%`, borderColor: "var(--signal-strong)" }}
          title={`SPOT: ${fmtPrice(spot)}`}
        />
        {magnet && (
          <div
            className="gex-range-marker"
            style={{
              left: `${pct(magnet)}%`,
              borderColor: "var(--signal-core)",
            }}
            title={`MAGNET: ${fmtPrice(magnet)}`}
          />
        )}
      </div>
      <div className="gex-range-labels">
        <span>{fmtPrice(low)}</span>
        {flip && (
          <span style={{ left: `${pct(flip)}%`, color: "var(--warning)" }}>
            {fmtPrice(flip)}
          </span>
        )}
        <span style={{ marginLeft: "auto" }}>{fmtPrice(high)}</span>
      </div>
      <div className="gex-range-sublabels">
        {accel && <span>MAX ACCEL</span>}
        {flip && <span>GEX FLIP</span>}
        <span>CLOSE</span>
        {magnet && <span>MAX MAGNET</span>}
      </div>
    </div>
  );
}

/* ─── History Table ──────────────────────────────────── */

type GexSortCol =
  | "date"
  | "net_gex"
  | "net_dex"
  | "gex_flip"
  | "spot"
  | "atm_iv"
  | "vol_pc"
  | "bias";
type SortDir = "asc" | "desc";

function sortIndicator(
  col: GexSortCol,
  activeCol: GexSortCol | null,
  dir: SortDir,
): string {
  if (col !== activeCol) return "";
  return dir === "asc" ? " \u2191" : " \u2193";
}

/* ─── MenthorQ Levels Panel ─────────────────────────── */

function MqLevelsPanel({
  mq,
  sourceDelta,
}: {
  mq: MqLevels;
  sourceDelta: SourceDelta | null;
}) {
  const [expanded, setExpanded] = useState(false);

  function deltaStyle(d: number | undefined): React.CSSProperties {
    if (d == null) return {};
    if (Math.abs(d) <= 2) return { color: "var(--signal-core)" };
    if (Math.abs(d) <= 10) return { color: "var(--warning)" };
    return { color: "var(--fault)" };
  }

  function fmtDelta(e: SourceDeltaEntry | undefined): React.ReactNode {
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
          {/* MQ Level Values */}
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

          {/* Source Delta */}
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
            {/* IV comparison */}
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

function GexHistoryTable({ history }: { history: GexHistoryEntry[] }) {
  const [sortCol, setSortCol] = useState<GexSortCol | null>(null);
  const [sortDir, setSortDir] = useState<SortDir>("desc");
  const [expanded, setExpanded] = useState(false);

  function handleSort(col: GexSortCol) {
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
    if (!sortCol) return history;
    return [...history].sort((a, b) => {
      const av = sortCol === "date" ? a.date : (a[sortCol] ?? -Infinity);
      const bv = sortCol === "date" ? b.date : (b[sortCol] ?? -Infinity);
      if (av < bv) return sortDir === "asc" ? -1 : 1;
      if (av > bv) return sortDir === "asc" ? 1 : -1;
      return 0;
    });
  }, [history, sortCol, sortDir]);

  if (!history.length) return null;

  const cols: { key: GexSortCol; label: string; align: string }[] = [
    { key: "date", label: "Date", align: "left" },
    { key: "spot", label: "Spot", align: "right" },
    { key: "gex_flip", label: "GEX Flip", align: "right" },
    { key: "net_gex", label: "Net GEX", align: "right" },
    { key: "net_dex", label: "Net DEX", align: "right" },
    { key: "atm_iv", label: "IV 30D", align: "right" },
    { key: "vol_pc", label: "Vol P/C", align: "right" },
    { key: "bias", label: "Bias", align: "center" },
  ];

  return (
    <div className="gex-history-section">
      <button
        className="gex-history-toggle"
        onClick={() => setExpanded(!expanded)}
      >
        History ({history.length} sessions) {expanded ? "\u25B2" : "\u25BC"}
      </button>
      {expanded && (
        <div className="gex-history-table-wrap">
          <table className="gex-history-table">
            <thead>
              <tr>
                {cols.map((c) => (
                  <th
                    key={c.key}
                    className={`text-${c.align}`}
                    onClick={() => handleSort(c.key)}
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
                  <td className="text-right">{fmtPrice(row.spot)}</td>
                  <td className="text-right">{fmtPrice(row.gex_flip)}</td>
                  <td
                    className="text-right"
                    style={{
                      color:
                        row.net_gex >= 0
                          ? "var(--signal-core)"
                          : "var(--fault)",
                    }}
                  >
                    {fmtGex(row.net_gex)}
                  </td>
                  <td className="text-right">{fmtGex(row.net_dex)}</td>
                  <td className="text-right">
                    {row.atm_iv != null ? `${row.atm_iv.toFixed(1)}%` : "---"}
                  </td>
                  <td className="text-right">
                    {row.vol_pc != null ? row.vol_pc.toFixed(2) : "---"}
                  </td>
                  <td className="text-center">
                    <span
                      style={{
                        color: biasColor(row.bias || "NEUTRAL"),
                        fontWeight: 600,
                        fontSize: 10,
                      }}
                    >
                      {biasLabel(row.bias || "NEUTRAL")}
                    </span>
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

/* ─── Main component ─────────────────────────────────── */

export default function GexSubTab({ marketState }: GexSubTabProps) {
  const { data, loading, error, lastSync } = useGex(marketState ?? null);

  if (loading && !data) {
    return (
      <div className="section">
        <div className="section-header">
          <div className="section-title">
            <Activity size={14} />
            Gamma Exposure Levels
          </div>
        </div>
        <div
          className="section-body"
          style={{ padding: "24px", textAlign: "center" }}
        >
          <span
            style={{
              fontFamily: "var(--font-mono)",
              fontSize: "11px",
              color: "var(--text-muted)",
            }}
          >
            Loading GEX scan...
          </span>
        </div>
      </div>
    );
  }

  if (error && !data) {
    return (
      <div className="section">
        <div className="section-header">
          <div className="section-title">
            <Activity size={14} />
            Gamma Exposure Levels
          </div>
        </div>
        <div className="section-body" style={{ padding: "16px" }}>
          <div className="alert-item bearish">{error}</div>
        </div>
      </div>
    );
  }

  if (!data || (!data.spot && !data.profile?.length)) {
    return (
      <div className="section">
        <div className="section-header">
          <div className="section-title">
            <Activity size={14} />
            Gamma Exposure Levels
          </div>
        </div>
        <div
          className="section-body"
          style={{ padding: "24px", textAlign: "center" }}
        >
          <span
            style={{
              fontFamily: "var(--font-mono)",
              fontSize: "11px",
              color: "var(--text-muted)",
            }}
          >
            No GEX data available — run a scan to populate.
          </span>
        </div>
      </div>
    );
  }

  const { bias, levels } = data;
  const daysAbove = bias.days_above_flip;
  const daysSide = daysAbove > 0 ? "ABOVE" : daysAbove < 0 ? "BELOW" : "AT";
  const daysCount = Math.abs(daysAbove);
  const spotFreshnessAnchorMs = Date.parse(lastSync ?? data.scan_time);

  const netGexColor = data.net_gex >= 0 ? "var(--signal-core)" : "var(--fault)";
  const netDexColor = data.net_dex >= 0 ? "var(--signal-core)" : "var(--fault)";

  return (
    <div className="section gex-panel">
      {/* ── Header ── */}
      <div className="section-header">
        <div className="section-title">
          <Activity size={14} />
          {data.ticker} Gamma Exposure Levels &mdash; {data.data_date}
          <InfoTooltip
            text="Gamma Exposure (GEX): net dealer gamma by strike. Positive = dealers long gamma (stabilizing, pins price). Negative = dealers short gamma (destabilizing, amplifies moves). Sources: Unusual Whales + MenthorQ."
            triggerTestId="gex-section-tooltip-trigger"
            contentTestId="gex-section-tooltip-content"
          />
        </div>
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: 10,
            flexWrap: "wrap",
          }}
        >
          {daysCount > 0 && (
            <span
              className="gex-day-badge"
              style={{
                background:
                  daysAbove > 0 ? "var(--signal-deep)" : "var(--fault)",
                color: "#fff",
              }}
            >
              DAY {daysCount} {daysSide} GEX FLIP
            </span>
          )}
          {lastSync && (
            <span
              style={{
                fontFamily: "var(--font-mono)",
                fontSize: 10,
                color: "var(--text-muted)",
              }}
            >
              {new Date(lastSync).toLocaleTimeString()}
            </span>
          )}
        </div>
      </div>

      <div
        className="section-body"
        style={{ display: "flex", flexDirection: "column", gap: 16 }}
      >
        {/* ── Metrics Row ── */}
        <div className="gex-metrics-row">
          <MetricCard
            label="SPOT"
            badge={
              <SpotFreshnessPill
                tapeTime={data.tape_time}
                nowMs={
                  Number.isFinite(spotFreshnessAnchorMs)
                    ? spotFreshnessAnchorMs
                    : undefined
                }
              />
            }
            value={fmtPrice(data.spot)}
            sub={
              data.day_change != null ? (
                <span
                  style={{
                    color:
                      data.day_change >= 0
                        ? "var(--positive)"
                        : "var(--negative)",
                  }}
                >
                  {data.day_change >= 0 ? "+" : ""}
                  {fmtPrice(data.day_change)} ({formatPercent(data.day_change_pct)})
                </span>
              ) : undefined
            }
          />
          <MetricCard
            label="GEX FLIP"
            tooltip="The strike where net GEX crosses from negative (destabilizing) to positive (stabilizing). Spot above flip = dealers long gamma; below = short gamma. MQ HVL shown when UW flip uncomputable."
            value={
              levels.gex_flip
                ? fmtPrice(levels.gex_flip.strike)
                : data.mq?.hvl
                  ? fmtPrice(data.mq.hvl as number)
                  : "---"
            }
            sub={
              levels.gex_flip
                ? `${formatPercent(levels.gex_flip.distance_pct)} from spot`
                : data.mq?.hvl
                  ? "MQ HVL"
                  : undefined
            }
            color="var(--warning)"
            badge={
              levels.gex_flip ? (
                <SourceBadge source="uw" />
              ) : data.mq?.hvl ? (
                <SourceBadge source="mq" />
              ) : undefined
            }
          />
          <MetricCard
            label="NET GEX"
            tooltip="Net dealer gamma exposure in dollars. Negative = dealers short gamma (amplifies moves). Positive = dealers long gamma (stabilizes price)."
            value={fmtGex(data.net_gex)}
            color={netGexColor}
            badge={<SourceBadge source="uw" />}
          />
          <MetricCard
            label="NET DEX"
            tooltip="Net dealer delta exposure. Negative = dealers net short delta (will sell on rallies). Large negative DEX signals structural selling pressure."
            value={fmtGex(data.net_dex)}
            color={netDexColor}
            badge={<SourceBadge source="uw" />}
          />
          <MetricCard
            label="IV 30D"
            tooltip="30-day implied volatility from UW iv_rank endpoint (not 0DTE greeks). Source-tagged: UW = Unusual Whales, MQ = MenthorQ, UW+MQ = both sources agree."
            value={
              data.iv?.iv30d != null
                ? `${data.iv.iv30d.toFixed(1)}%`
                : data.iv?.mq_iv30d != null
                  ? `${data.iv.mq_iv30d.toFixed(1)}%`
                  : data.atm_iv != null
                    ? `${data.atm_iv.toFixed(1)}%`
                    : "---"
            }
            sub={
              data.iv?.iv_rank != null
                ? `rank ${data.iv.iv_rank.toFixed(0)}%${data.iv.hv30 != null ? `  HV ${data.iv.hv30.toFixed(1)}%` : ""}`
                : data.expected_range.iv_1d != null
                  ? `±${data.expected_range.iv_1d.toFixed(2)}% 1d`
                  : undefined
            }
            badge={
              data.iv?.source ? (
                <SourceBadge source={data.iv.source} />
              ) : undefined
            }
          />
          <MetricCard
            label="VOL P/C"
            value={data.vol_pc != null ? data.vol_pc.toFixed(2) : "---"}
            color={
              data.vol_pc != null && data.vol_pc > 1.2
                ? "var(--warning)"
                : undefined
            }
            badge={<SourceBadge source="uw" />}
          />
        </div>

        {/* ── Key Levels Row (UW) ── */}
        <div className="gex-levels-row">
          <LevelCard
            label="GEX FLIP (SUPPORT)"
            level={levels.gex_flip}
            labelColor="var(--warning)"
          />
          <LevelCard
            label="MAX MAGNET"
            level={levels.max_magnet}
            labelColor="var(--signal-core)"
          />
          <LevelCard
            label="2ND MAGNET"
            level={levels.second_magnet}
            labelColor="var(--signal-core)"
          />
          <LevelCard
            label="MAX ACCEL (BELOW FLIP)"
            level={levels.max_accelerator}
            labelColor="var(--fault)"
          />
          <LevelCard
            label="PUT WALL"
            level={levels.put_wall}
            labelColor="var(--fault)"
          />
        </div>

        {/* ── MenthorQ Levels + Delta ── */}
        {data.mq && (
          <MqLevelsPanel
            mq={data.mq as MqLevels}
            sourceDelta={data.source_delta as SourceDelta | null}
          />
        )}

        {/* ── GEX Profile Chart ── */}
        <GexProfileChart profile={data.profile} spot={data.spot} />

        {/* ── Bottom Row: Expected Range + Bias ── */}
        <div className="gex-bottom-row">
          <ExpectedRangeBar data={data} />
          <div className="gex-bias-card">
            <div className="gex-bias-title">DIRECTIONAL BIAS</div>
            <div
              className="gex-bias-direction"
              style={{ color: biasColor(bias.direction) }}
            >
              {biasLabel(bias.direction)}
              {bias.direction.includes("BULL") ? (
                <TrendingUp size={24} style={{ marginLeft: 8 }} />
              ) : bias.direction.includes("BEAR") ? (
                <TrendingDown size={24} style={{ marginLeft: 8 }} />
              ) : null}
            </div>
            <div className="gex-bias-reasons">
              {bias.reasons.map((r, i) => (
                <div key={i} className="gex-bias-reason">
                  {r}
                </div>
              ))}
            </div>
            {bias.flip_migration.length > 1 && (
              <div className="gex-flip-migration">
                Flip migration:{" "}
                {bias.flip_migration.map((f) => fmtPrice(f.flip)).join(" → ")}
              </div>
            )}
          </div>
        </div>

        {/* ── 90-day History Chart (net_gex / flip / spot) ── */}
        <HistoryChart history={data.history} ticker={data.ticker} />

        {/* ── History Table ── */}
        <GexHistoryTable history={data.history} />
      </div>
    </div>
  );
}
