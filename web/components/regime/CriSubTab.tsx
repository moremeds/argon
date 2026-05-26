"use client";

import { AlertTriangle, Check, Shield, X, Zap } from "lucide-react";

import CriHistoryChart, {
  type ChartSeries,
  type CriHistoryEntry,
} from "./CriHistoryChart";
import InfoTooltip from "./InfoTooltip";
import { CriHistoryTable } from "./cri/CriHistoryTable";
import { GuidancePanel } from "./GuidancePanel";
import { MeanReversionTiles } from "./MeanReversionTiles";
import { ComponentBar, type ComponentSlot } from "./primitives/ComponentBar";
import {
  DayChange,
  LiveBadge,
  PointChange,
  RegimeStrip,
  RegimeStripCell,
} from "./RegimeStrip";
import {
  formatNumber,
  formatPercent,
  formatSignedNumber,
} from "./primitives/format";
import { type CriBlock, type CriResponse, useCri } from "@/lib/regime/useCri";

type CriLevel = "LOW" | "ELEVATED" | "HIGH" | "CRITICAL";

// Mirror the Python scoring math from src/uw_scan/cards/cri_scorers.py so we
// can draw the prior-day dot on each ComponentBar. Floors/ceilings MUST match
// cri-methodology.md §3.
//
// v3 (2026-05-20): VIX floor 13 + RoC denom 40; VVIX floor 80; momentum
// reshaped into structural (0-15) + tactical (0-10) sub-scores.
//
// Exported for unit testing — see web/tests/unit/CriSubTab.priorScore.test.tsx.
export function priorComponentScore(
  prior: CriHistoryEntry | undefined,
  slot: ComponentSlot,
): number | null {
  if (!prior) return null;
  const clip = (x: number, lo: number, hi: number) =>
    Math.max(lo, Math.min(hi, x));
  const round1 = (x: number) => Math.round(x * 10) / 10;
  if (slot === "vix") {
    // v3: floor 13, RoC denom 40 (was 15 / 60)
    if (prior.vix == null || prior.vix_5d_roc == null) return null;
    const lvl = clip(((prior.vix - 13) / 27) * 15, 0, 15);
    const roc = clip((Math.max(prior.vix_5d_roc, 0) / 40) * 10, 0, 10);
    return round1(lvl + roc);
  }
  if (slot === "vvix") {
    // v3: level floor 80 (was 85); ratio band 5-8 and RoC denom 25 unchanged
    if (prior.vvix == null || prior.vix == null || prior.vix <= 0) return null;
    const ratio = prior.vvix / prior.vix;
    const lvl = clip(((prior.vvix - 80) / 50) * 12, 0, 12);
    const r = clip(((ratio - 5) / 3) * 7, 0, 7);
    // vvix_5d_roc was added in v2 — historical snapshots may not have it.
    const rocRaw = prior.vvix_5d_roc ?? 0;
    const roc = clip((Math.max(rocRaw, 0) / 25) * 6, 0, 6);
    return round1(lvl + r + roc);
  }
  if (slot === "correlation") {
    // Unchanged across versions
    if (prior.cor1m == null) return null;
    const lvl = clip(((prior.cor1m - 25) / 45) * 17, 0, 17);
    const chg = prior.cor1m_5d_change ?? 0;
    const spike = clip((Math.max(chg, 0) / 20) * 8, 0, 8);
    return round1(lvl + spike);
  }
  if (slot === "momentum") {
    // v3: structural (0-15, vs 100d MA) + tactical (0-10, vs 20d high, sat -4%)
    if (prior.spx_vs_ma_pct == null) return null;
    const d = prior.spx_vs_ma_pct;
    const structural = d >= 0 ? 0 : clip((Math.abs(d) / 10) * 15, 0, 15);
    // pullback_20d_pct is a v3 history-entry field. Historical (pre-v3) rows
    // won't have it; default to 0 (tactical sub-score doesn't fire).
    const pullback = prior.pullback_20d_pct ?? 0;
    const tactical =
      pullback >= 0 ? 0 : clip((Math.abs(pullback) / 4) * 10, 0, 10);
    return round1(clip(structural + tactical, 0, 25));
  }
  return null;
}

const SECTION_TOOLTIPS: Record<string, string> = {
  "CRI COMPONENTS":
    "Crash Risk Index broken into 4 sub-scores (0-25 each, 100 total). VIX/VVIX measure implied vol stress. Correlation tracks COR1M herding. Trend Break fires when SPX trades below its 100-day MA. See docs/research/regime/cri-methodology.md for calibration details.",
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

export function CriSubTabView({
  data,
  onSyncNow,
  syncing = false,
}: {
  data: CriResponse | null;
  onSyncNow?: () => void;
  syncing?: boolean;
}) {
  // Empty/loading state — mirrors xenon's "no CRI data" shield empty.
  if (!data || data.status === "empty") {
    return (
      <div className="regime-empty" data-testid="cri-empty-state">
        <Shield size={32} strokeWidth={1} />
        <p>No CRI data available. Click Sync Now to run a scan.</p>
        {onSyncNow && (
          <button
            type="button"
            onClick={onSyncNow}
            disabled={syncing}
            data-testid="cri-sync-now"
            style={{
              marginTop: "12px",
              padding: "6px 14px",
              fontFamily: "var(--font-mono)",
              fontSize: "11px",
              letterSpacing: "0.08em",
              textTransform: "uppercase",
              background: "var(--bg-panel-raised, var(--bg-panel))",
              border: "1px solid var(--border-dim, var(--line-grid))",
              color: "var(--text-primary)",
              cursor: syncing ? "default" : "pointer",
              opacity: syncing ? 0.6 : 1,
            }}
          >
            {syncing ? "Syncing…" : "Sync Now"}
          </button>
        )}
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
  const liveValues = {};
  // Second-to-last row drives the prior-day dot on each ComponentBar.
  const priorHistory =
    history.length >= 2 ? history[history.length - 2] : undefined;

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
          value={formatNumber(vix)}
          change={<DayChange last={vix} close={vixClose} />}
          sub={<>5d RoC: {formatPercent(data.vix_5d_roc, 1)}</>}
        />
        <RegimeStripCell
          testId="strip-vvix"
          label={
            <>
              VVIX <LiveBadge live={live} />
            </>
          }
          value={formatNumber(vvix)}
          change={<DayChange last={vvix} close={vvixClose} />}
          sub={<>VVIX/VIX: {formatNumber(vvixVixRatio)}</>}
        />
        <RegimeStripCell
          testId="strip-spy"
          label={
            <>
              {data.spx_source === "SPY" ? "SPY" : "SPX"}{" "}
              <LiveBadge live={live} />
            </>
          }
          value={`$${formatNumber(spy)}`}
          change={<DayChange last={spy} close={spyClose} prefix="$" />}
          sub={<>vs 100d MA: {formatPercent(spxDistPct)}</>}
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
          value={realizedVol != null ? `${formatNumber(realizedVol)}%` : "---"}
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
          value={formatNumber(cor1m, 2)}
          change={<DayChange last={cor1m} close={cor1mPrevClose} />}
          sub={
            <>{`5d chg: ${corr5dChange != null ? `${formatSignedNumber(corr5dChange)} pts` : "---"}`}</>
          }
        />
      </RegimeStrip>

      {/* ── Mean-reversion tiles (VRP / VIX z-score / VIX-VIX3M ratio / VIX Δ 3d) ── */}
      <MeanReversionTiles
        vrp={data.vrp ?? null}
        vixZscore={data.vix_zscore_30d ?? null}
        vixVix3mRatio={data.vix_vix3m_ratio ?? null}
        vixDelta3d={data.vix_delta_3d ?? null}
      />

      {/* ── Row 3+4: Components + Crash trigger ── */}
      <div className="regime-detail-grid">
        <div className="regime-components">
          <div className="regime-panel-title">
            <Zap size={12} />
            CRI COMPONENTS
            <InfoTooltip text={SECTION_TOOLTIPS["CRI COMPONENTS"]} />
          </div>
          <ComponentBar
            label="VIX"
            slot="vix"
            score={components.vix}
            priorScore={priorComponentScore(priorHistory, "vix")}
            live={live}
          />
          <ComponentBar
            label="VVIX"
            slot="vvix"
            score={components.vvix}
            priorScore={priorComponentScore(priorHistory, "vvix")}
            live={live}
          />
          <ComponentBar
            label="CORRELATION"
            slot="correlation"
            score={components.correlation}
            priorScore={priorComponentScore(priorHistory, "correlation")}
            live={live}
          />
          <ComponentBar
            label="TREND BREAK"
            slot="momentum"
            score={components.momentum}
            priorScore={priorComponentScore(priorHistory, "momentum")}
            live={live}
          />
          {data.pullback_20d_pct != null && data.pullback_20d_pct < 0 && (
            <div
              className="regime-component-subtext"
              data-testid="trend-break-pullback-line"
            >
              Pullback: {data.pullback_20d_pct.toFixed(2)}% from 20d high
            </div>
          )}
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
            value={`${formatPercent(spxDistPct)} (MA: $${formatNumber(ma)})`}
            live={live}
          />
          <TriggerRow
            label="Realized Vol > 25%"
            met={rvolTriggerMet}
            value={
              realizedVol != null ? `${formatNumber(realizedVol)}%` : "---"
            }
            live={live}
          />
          <TriggerRow
            label="COR1M > 60"
            met={correlationTriggerMet}
            value={formatNumber(cor1m, 2)}
            live={live}
          />
        </div>
      </div>

      {/* ── Regime guidance (markdown-driven via /api/regime/guidance) ── */}
      <GuidancePanel />

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
  const { data, syncing, syncNow } = useCri();
  return <CriSubTabView data={data} syncing={syncing} onSyncNow={syncNow} />;
}
