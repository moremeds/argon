"use client";

import { useState } from "react";

import InfoTooltip from "./InfoTooltip";
import { regimeApi } from "@/lib/regime/api";
import { useVrpMacroLive } from "@/lib/regime/useVrpMacroLive";
import {
  useVrpMacroEntryPreview,
  type VrpMacroEntryLeg,
} from "@/lib/regime/useVrpMacroEntryPreview";

const pct = (x: number | null | undefined) =>
  x == null ? "—" : `${(x * 100).toFixed(1)}%`;
const f = (x: number | null | undefined, d = 2) =>
  x == null ? "—" : x.toFixed(d);

const legMid = (l: VrpMacroEntryLeg): number | null =>
  l.nbbo_bid != null && l.nbbo_ask != null
    ? (l.nbbo_bid + l.nbbo_ask) / 2
    : null;

// leg-name → display label (Δ magnitude + bracket side)
const LEG_LABEL: Record<string, string> = {
  short_above: "0.25↑",
  short_below: "0.25↓",
  wing_above: "0.125↑",
  wing_below: "0.125↓",
};
const LEG_ORDER = ["short_above", "short_below", "wing_above", "wing_below"];

/**
 * Macro short-vol readout for SPX, rendered as a sibling of the GEX Directional
 * Bias card (same `.gex-bias-*` styling). The action (TRADE/SKIP) is the big
 * headline; reasons sit underneath. The right panel shows the tracked entry
 * (ETD + the 4 bracketing puts) served from today's persisted cohort snapshot
 * (or BS-indicative pre-birth), plus a one-click Capture button.
 */
export default function MacroShortVolCard() {
  const { data, loading } = useVrpMacroLive();
  const { data: preview } = useVrpMacroEntryPreview();
  const [capturing, setCapturing] = useState(false);
  const [capturedId, setCapturedId] = useState<number | null>(null);
  const [captureError, setCaptureError] = useState(false);

  const capture = async () => {
    if (capturing) return; // debounce: one-shot, non-idempotent write
    setCapturing(true);
    setCaptureError(false);
    try {
      const res = await fetch(regimeApi.vrp_macro_entry_capture(), {
        method: "POST",
      });
      if (!res.ok) throw new Error(String(res.status));
      const body = await res.json();
      setCapturedId(body.entry_id ?? null);
    } catch {
      setCaptureError(true);
    } finally {
      setCapturing(false);
    }
  };

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
        `vrp_z ${f(s.vrp_z)} · weight ${f(s.weight)}`,
        `IV ${pct(s.iv)} / RV20 ${pct(s.rv20)}`,
      ];

  const legs = (preview?.legs ?? [])
    .slice()
    .sort((a, b) => LEG_ORDER.indexOf(a.leg) - LEG_ORDER.indexOf(b.leg));

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

      <div style={{ display: "flex", gap: 16, alignItems: "flex-start" }}>
        {/* left: action + reasons */}
        <div style={{ flex: 1, minWidth: 0 }}>
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
            Bull put spread {s.short_delta}Δ/{s.wing_delta}Δ · ~{s.hold_days}d
            hold
          </div>
        </div>

        {/* right: tracked-entry preview panel */}
        <div
          style={{
            flex: 1,
            minWidth: 0,
            borderLeft: "1px solid var(--border-dim)",
            paddingLeft: 16,
          }}
        >
          <div
            style={{
              fontFamily: "var(--font-mono)",
              fontSize: 9,
              color: "var(--text-muted)",
              textTransform: "uppercase",
              letterSpacing: "1.5px",
              marginBottom: 6,
            }}
          >
            Tracked entry · ETD {preview?.expiry ?? "—"}
          </div>
          {legs.length === 0 ? (
            <div className="gex-bias-reason">No entry preview yet.</div>
          ) : (
            <table
              style={{
                width: "100%",
                fontFamily: "var(--font-mono)",
                fontSize: 11,
                borderCollapse: "collapse",
              }}
            >
              <tbody>
                {legs.map((l) => (
                  <tr key={l.leg} data-testid={`entry-leg-${l.leg}`}>
                    <td style={{ color: "var(--text-muted)" }}>
                      {LEG_LABEL[l.leg] ?? l.leg}
                    </td>
                    <td style={{ textAlign: "right" }}>{f(l.strike, 0)}</td>
                    <td
                      style={{ textAlign: "right", color: "var(--text-muted)" }}
                    >
                      {f(legMid(l))}
                    </td>
                    <td
                      style={{ textAlign: "right", color: "var(--text-muted)" }}
                    >
                      {f(l.delta)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          <div
            style={{
              marginTop: 8,
              display: "flex",
              alignItems: "center",
              gap: 8,
            }}
          >
            <button
              type="button"
              onClick={capture}
              disabled={capturing}
              data-testid="capture-entry-btn"
              style={{
                fontFamily: "var(--font-mono)",
                fontSize: 10,
                textTransform: "uppercase",
                letterSpacing: "0.5px",
                padding: "4px 10px",
                background: "var(--bg-panel)",
                border: "1px solid var(--border-dim)",
                color: "var(--text-primary)",
                cursor: capturing ? "default" : "pointer",
                opacity: capturing ? 0.5 : 1,
              }}
            >
              {capturing ? "Capturing…" : "Capture entry"}
            </button>
            {capturedId != null && (
              <span
                style={{
                  fontFamily: "var(--font-mono)",
                  fontSize: 10,
                  color: "var(--positive)",
                }}
              >
                Captured #{capturedId}
              </span>
            )}
            {captureError && (
              <span
                style={{
                  fontFamily: "var(--font-mono)",
                  fontSize: 10,
                  color: "var(--negative)",
                }}
              >
                Capture failed
              </span>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
