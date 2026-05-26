"use client";

import InfoTooltip from "../InfoTooltip";
import { LiveBadge } from "../RegimeStrip";

const COMPONENT_TOOLTIPS: Record<string, string> = {
  VIX: "CBOE Volatility Index — 30-day implied vol of SPX. Score rises as VIX exceeds 20 (elevated) and 30 (high).",
  VVIX: "Vol-of-VIX — expected volatility of VIX itself. Three sub-scores: absolute level (85→130), VVIX/VIX ratio (5→8 = practitioner warning band), and 5-day rate-of-change (rising VVIX vs flat VIX is the canonical lead signal of tail-hedging demand).",
  CORRELATION:
    "Cboe 1-Month Implied Correlation Index (COR1M). High COR1M (>60) means large-cap S&P names are expected to move together.",
  "TREND BREAK":
    "SPX distance below the 100-day MA. One-sided: scores 0 when SPX is at or above the MA; saturates at -10% below. Designed to fire only on confirmed downtrends, not parabolic uptrends.",
};

export type ComponentSlot = "vix" | "vvix" | "correlation" | "momentum";

const COMPONENT_REFERENCES: Record<
  ComponentSlot,
  { mid: { score: number; label: string } }
> = {
  vix: { mid: { score: 5.0, label: "VIX 23" } },
  vvix: { mid: { score: 6.7, label: "VVIX 110" } },
  correlation: { mid: { score: 13.0, label: "COR1M 60" } },
  momentum: { mid: { score: 7.5, label: "-3% MA" } },
};

export type ComponentBarProps = {
  label: string;
  score: number;
  max?: number;
  slot?: ComponentSlot;
  priorScore?: number | null;
  live?: boolean;
};

export function ComponentBar({
  label,
  slot,
  score,
  max = 25,
  priorScore,
  live,
}: ComponentBarProps) {
  const pct = max > 0 ? (score / max) * 100 : 0;
  const clampedPct = Math.max(0, Math.min(100, pct));
  const barColor =
    slot == null
      ? "var(--positive)"
      : score < 8
        ? "var(--positive)"
        : score > 16
          ? "var(--negative)"
          : "var(--warning)";
  const tooltip = COMPONENT_TOOLTIPS[label];
  const ref = slot ? COMPONENT_REFERENCES[slot] : null;
  const midPct = ref && max > 0 ? (ref.mid.score / max) * 100 : null;
  const priorPct =
    priorScore != null && Number.isFinite(priorScore) && max > 0
      ? (Math.max(0, Math.min(max, priorScore)) / max) * 100
      : null;
  return (
    <div className="regime-component-bar">
      <div className="regime-component-label">
        <span style={{ flex: 1 }}>{label}</span>
        {tooltip && <InfoTooltip text={tooltip} />}
        {live != null && <LiveBadge live={live} />}
      </div>
      <div className="regime-bar-track" style={{ position: "relative" }}>
        <div
          className="regime-bar-fill"
          style={{ width: `${clampedPct}%`, background: barColor }}
        />
        {midPct != null && ref ? (
          <div
            className="regime-bar-tick"
            style={{
              position: "absolute",
              left: `${midPct}%`,
              top: 0,
              bottom: 0,
              width: 1,
              background: "var(--text-muted)",
              opacity: 0.5,
            }}
            title={ref.mid.label}
          />
        ) : null}
        {priorPct != null ? (
          <div
            className="regime-bar-prior"
            style={{
              position: "absolute",
              left: `${priorPct}%`,
              top: "50%",
              transform: "translate(-50%, -50%)",
              width: 6,
              height: 6,
              borderRadius: "50%",
              background: "var(--text-primary)",
              opacity: 0.7,
            }}
            title={`Prior: ${(priorScore as number).toFixed(1)}`}
          />
        ) : null}
      </div>
      <div className="regime-component-score">
        {score.toFixed(1)}/{max}
      </div>
    </div>
  );
}
