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
import { ComponentBar } from "./primitives/ComponentBar";
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
import CriSeriesGrids from "./cri/CriSeriesGrids";
import CardSparkline from "./primitives/CardSparkline";
import { type CriBlock } from "@/lib/regime/useCri";
import { useCriLive, type CriLiveResponse } from "@/lib/regime/useCriLive";
import { useCriDaily, type CriDailyEntry } from "@/lib/regime/useCriSeries";
import {
  criDailySeries,
  criPrevCloses,
  priorComponentScore,
  priorHistoryRow,
  spxMedianFiltered,
  vixDelta3dSeries,
  vvixVixRatio as vvixVixRatioDerive,
} from "@/lib/regime/derive/cri";
import { DispersionTiles } from "./DispersionTiles";
import { useDispersion, type DispersionData } from "@/lib/regime/useDispersion";

type CriLevel = "LOW" | "ELEVATED" | "HIGH" | "CRITICAL";

// priorComponentScore moved to @/lib/regime/derive/cri (verbatim — its
// constants must keep matching src/uw_scan/cards/cri_scorers.py); re-exported
// here so existing imports keep working.
export { priorComponentScore };

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

// prevClose / criPrevCloses / vvixVixRatio / the daily-series helpers moved
// verbatim to @/lib/regime/derive/cri.

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
  daily,
  dispersion,
  onSyncNow,
  syncing = false,
}: {
  data: CriLiveResponse | null;
  /** 90d daily history rows — drives the in-card sparklines. */
  daily?: CriDailyEntry[] | null;
  /** Descriptive correlation/dispersion context row (optional). */
  dispersion?: DispersionData | null;
  onSyncNow?: () => void;
  syncing?: boolean;
}) {
  // Empty/loading state — mirrors xenon's "no CRI data" shield empty.
  if (!data || data.status === "empty") {
    return (
      <div className="section gex-panel">
        <div className="section-header">
          <div className="section-title">
            <Shield size={14} />
            SPX Crash Risk Index (CRI)
          </div>
        </div>
        <div className="section-body">
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
        </div>
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

  const { vixClose, vvixClose, spyClose, cor1mPrevClose } =
    criPrevCloses(data);

  const corr5dChange = data.cor1m_5d_change ?? null;
  const vvixVixRatio = vvixVixRatioDerive(data);
  const spxDistPct = data.spx_distance_pct ?? null;
  const ma = data.spx_100d_ma ?? null;
  const trigger = data.crash_trigger;
  const triggered = trigger?.triggered ?? trigger?.fired ?? false;
  const correlationTriggerMet =
    trigger?.conditions?.cor1m_gt_60 ?? (cor1m != null && cor1m > 60);
  const spxBelowMa = trigger?.conditions?.spx_below_100d_ma ?? false;
  const rvolTriggerMet = trigger?.conditions?.realized_vol_gt_25 ?? false;

  // Live when the request-time compute ran off fresh WS quotes; falls back
  // to "eod"/CACHED when quotes are stale or the feed is down.
  const live = data.basis === "live";
  // Per-symbol chip: live only if that symbol's quote actually spliced
  // (a carried-forward symbol is yesterday's close, not a live tick).
  const liveFor = (sym: string): boolean =>
    live && !!data.live_quotes?.[sym] && !data.carried_forward?.includes(sym);
  const lastSync = data.scan_time || null;

  // History payload is the 20-session window (oldest → newest).
  const liveValues = {};
  // Second-to-last row drives the prior-day dot on each ComponentBar.
  const priorHistory = priorHistoryRow(data);

  // 90d daily series for in-card sparklines (oldest → newest).
  const dailyRows = daily ?? [];
  const dseries = (k: keyof CriDailyEntry): (number | null)[] =>
    criDailySeries(dailyRows, k);
  const vixDaily = dseries("vix");
  const vixDelta3dDaily = vixDelta3dSeries(dailyRows);
  const spxDaily = spxMedianFiltered(dailyRows).series;

  return (
    <div className="section gex-panel" data-testid="cri-subtab">
      <div className="section-header">
        <div className="section-title">
          <Shield size={14} />
          SPX Crash Risk Index (CRI)
        </div>
      </div>
      <div className="section-body regime-panel">
        {/* ── Row 1: Hero ───────────────────── */}
        <div className="regime-hero">
          <div className="regime-hero-top">
            <div className="regime-hero-main">
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
                  style={{
                    background: live ? "var(--positive)" : "var(--text-muted)",
                  }}
                />
                <span className="regime-hero-label">
                  {live
                    ? `LIVE${data.active_source ? ` · ${data.active_source === "xenon_ws" ? "XENON" : "MASSIVE"}` : ""}`
                    : "CACHED"}
                </span>
                {lastSync && (
                  <span className="regime-hero-timestamp">
                    Last scan: {new Date(lastSync).toLocaleTimeString()}
                  </span>
                )}
              </div>
            </div>
            {dailyRows.length > 0 && (
              <div className="regime-hero-spark" data-testid="cri-hero-spark">
                <div className="regime-hero-spark-label">CRI — DAILY 90D</div>
                <CardSparkline
                  values={dseries("cri_score")}
                  label="CRI daily score, 90 days"
                  color="var(--accent-warm, #F5A623)"
                  height={48}
                />
              </div>
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
                VIX <LiveBadge live={liveFor("VIX")} />
              </>
            }
            value={formatNumber(vix)}
            change={<DayChange last={vix} close={vixClose} />}
            sub={<>5d RoC: {formatPercent(data.vix_5d_roc, 1)}</>}
            spark={<CardSparkline values={vixDaily} label="VIX daily, 90d" />}
          />
          <RegimeStripCell
            testId="strip-vvix"
            label={
              <>
                VVIX <LiveBadge live={liveFor("VVIX")} />
              </>
            }
            value={formatNumber(vvix)}
            change={<DayChange last={vvix} close={vvixClose} />}
            sub={<>VVIX/VIX: {formatNumber(vvixVixRatio)}</>}
            spark={
              <CardSparkline
                values={dseries("vvix")}
                label="VVIX daily, 90d"
                color="var(--accent-vol, #8B5CF6)"
              />
            }
          />
          <RegimeStripCell
            testId="strip-spy"
            label={
              <>
                {data.spx_source === "SPY" ? "SPY" : "SPX"}{" "}
                <LiveBadge live={liveFor("SPX")} />
              </>
            }
            value={`$${formatNumber(spy)}`}
            change={<DayChange last={spy} close={spyClose} prefix="$" />}
            sub={<>vs 100d MA: {formatPercent(spxDistPct)}</>}
            spark={
              <CardSparkline
                values={spxDaily}
                label="SPX daily, 90d"
                color="var(--text-primary)"
              />
            }
          />
          <RegimeStripCell
            testId="strip-rvol"
            label={
              <>
                <span className="regime-strip-label-text-full">
                  REALIZED VOL
                </span>
                <span className="regime-strip-label-text-short">RVOL</span>
                <LiveBadge live={live} />
              </>
            }
            value={
              realizedVol != null ? `${formatNumber(realizedVol)}%` : "---"
            }
            change={<PointChange change={null} suffix="%" label="intraday" />}
            sub={<>20d annualized</>}
            spark={
              <CardSparkline
                values={dseries("realized_vol")}
                label="Realized vol daily, 90d"
              />
            }
          />
          <RegimeStripCell
            testId="strip-cor1m"
            label={
              <>
                COR1M <LiveBadge live={liveFor("COR1M")} />
              </>
            }
            value={formatNumber(cor1m, 2)}
            change={<DayChange last={cor1m} close={cor1mPrevClose} />}
            sub={
              <>{`5d chg: ${corr5dChange != null ? `${formatSignedNumber(corr5dChange)} pts` : "---"}`}</>
            }
            spark={
              <CardSparkline
                values={dseries("cor1m")}
                label="COR1M daily, 90d"
              />
            }
          />
        </RegimeStrip>

        {/* ── Mean-reversion tiles (VRP / VIX z-score / VIX-VIX3M ratio / VIX Δ 3d) ── */}
        <MeanReversionTiles
          vrp={data.vrp ?? null}
          vixZscore={data.vix_zscore_30d ?? null}
          vixVix3mRatio={data.vix_vix3m_ratio ?? null}
          vixDelta3d={data.vix_delta_3d ?? null}
          series={
            dailyRows.length > 0
              ? {
                  vrp: dseries("vrp"),
                  vixZscore: dseries("vix_zscore_30d"),
                  vixVix3mRatio: dseries("vix_vix3m_ratio"),
                  vixDelta3d: vixDelta3dDaily,
                }
              : undefined
          }
        />

        {/* ── Dispersion context (COR1M %ile + VIX/COR1M ratio & z) ── */}
        <DispersionTiles data={dispersion ?? null} />

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
              <InfoTooltip
                text={SECTION_TOOLTIPS["CRASH TRIGGER CONDITIONS"]}
              />
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
          </>
        )}

        {/* ── Row 6: Intraday small-multiples grid (basis='live' rows) ── */}
        <CriSeriesGrids />

        {/* ── Row 7: Historical table (folded by default) ── */}
        {history.length > 0 && <CriHistoryTable history={history} />}
      </div>
    </div>
  );
}

export default function CriSubTab() {
  const { data, syncing, syncNow } = useCriLive();
  const { data: daily } = useCriDaily(90);
  const dispersion = useDispersion();
  return (
    <CriSubTabView
      data={data}
      daily={daily?.rows ?? null}
      dispersion={dispersion}
      syncing={syncing}
      onSyncNow={syncNow}
    />
  );
}
