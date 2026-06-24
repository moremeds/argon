"use client";

import InfoTooltip from "./InfoTooltip";
import { useVrpMacroLive } from "@/lib/regime/useVrpMacroLive";

const pct = (x: number | null | undefined) =>
  x == null ? "—" : `${(x * 100).toFixed(1)}%`;
const f = (x: number | null | undefined, d = 2) =>
  x == null ? "—" : x.toFixed(d);

/**
 * Macro short-vol readout for SPX, rendered as a sibling of the GEX Directional
 * Bias card (same `.gex-bias-*` styling). The action (TRADE/SKIP) is the big
 * headline; reasons sit underneath as bullets. Recomputes live every 30s via
 * useVrpMacroLive; falls back to the latest EOD snapshot when no live quote.
 */
export default function MacroShortVolCard() {
  const { data, loading } = useVrpMacroLive();

  const title = (
    <div className="gex-bias-title" style={{ marginBottom: 0 }}>
      MACRO SHORT-VOL · SPX
      <InfoTooltip
        text="Sell index VRP via a bull put spread (0.25Δ short / 0.125Δ wing, ~30-trading-day hold, weekly). Gated and SIZED by vrp_z (IV − RV20, z-scored vs trailing 252d): weight = how much of base risk to deploy — 0 at vrp_z≤0 (SKIP), ramping to 1.0 (full size) at vrp_z≥0.5. Credit is flat-vol modeled (conservative floor; real put-skew credit is higher). Backtest Sharpe is in-sample-tuned over 2006–2026 — discount to ~1.3–1.6 live."
        triggerTestId="macro-shortvol-tooltip-trigger"
        contentTestId="macro-shortvol-tooltip-content"
      />
    </div>
  );

  if (loading && !data) {
    return (
      <div className="gex-bias-card">
        {title}
        <div className="gex-bias-reason" style={{ marginTop: 12 }}>
          Loading…
        </div>
      </div>
    );
  }

  const s = data?.signal;
  if (!s) {
    return (
      <div className="gex-bias-card">
        {title}
        <div className="gex-bias-reason" style={{ marginTop: 12 }}>
          No signal yet (no live quote and no EOD snapshot).
        </div>
      </div>
    );
  }

  const trade = s.action === "TRADE";
  const color = trade ? "var(--positive)" : "var(--text-muted)";
  const reasons = trade
    ? [
        `vrp_z ${f(s.vrp_z)} · weight ${f(s.weight)} (size)`,
        `Sell ${f(s.short_put, 0)} / buy ${f(s.long_put, 0)} put`,
        `Credit ${f(s.credit)} · max loss ${f(s.max_loss)} per spread`,
      ]
    : [
        `vrp_z ${f(s.vrp_z)} · weight ${f(s.weight)} (gate at 0)`,
        `IV ${pct(s.iv)} / RV20 ${pct(s.rv20)}`,
        "Vol not rich enough — stand aside",
      ];

  return (
    <div className="gex-bias-card">
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          marginBottom: 8,
        }}
      >
        {title}
        <span
          style={{
            fontFamily: "var(--font-mono)",
            fontSize: 9,
            color: "var(--text-muted)",
            textTransform: "uppercase",
            letterSpacing: "0.5px",
          }}
        >
          {data?.basis === "live"
            ? `live · ${data?.active_source ?? ""}`
            : "EOD snapshot"}
        </span>
      </div>
      <div className="gex-bias-direction" style={{ color }}>
        {s.action}
      </div>
      <div className="gex-bias-reasons">
        {reasons.map((r, i) => (
          <div key={i} className="gex-bias-reason">
            {r}
          </div>
        ))}
      </div>
      <div className="gex-flip-migration">
        Bull put spread {s.short_delta}Δ/{s.wing_delta}Δ · ~{s.hold_days}d hold
      </div>
    </div>
  );
}
