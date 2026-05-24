"use client";

import { Activity, TrendingUp, TrendingDown } from "lucide-react";
import {
  useGex,
  type GexLevel,
  type MqLevels,
  type SourceDelta,
} from "@/lib/regime/useGex";
import { MarketState } from "@/lib/regime/useMarketHours";
import InfoTooltip from "./InfoTooltip";
import GexProfileChart from "./GexProfileChart";
import { HistoryChart } from "./HistoryChart";
import { ExpectedRangeBar } from "./gex/ExpectedRangeBar";
import { GexHistoryTable } from "./gex/GexHistoryTable";
import { MqLevelsPanel } from "./gex/MqLevelsPanel";
import { biasColor, biasLabel, fmtGex, fmtPrice } from "./gex/format";
import { formatPercent } from "./primitives/format";
import { MetricCard, SourceBadge } from "./ui/MetricCard";

type GexSubTabProps = {
  marketState?: MarketState;
};

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
