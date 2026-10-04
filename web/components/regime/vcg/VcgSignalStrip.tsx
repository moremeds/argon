"use client";

import { AlertTriangle, TrendingUp, Zap } from "lucide-react";

import InfoTooltip from "../InfoTooltip";
import CardSparkline from "../primitives/CardSparkline";
import {
  formatNumber,
  formatPercent,
  formatSignedNumber,
} from "../primitives/format";
import { type VcgSignal } from "@/lib/regime/useVcg";
import { type VcgLiveResponse } from "@/lib/regime/useVcgLive";
import { type VcgDailyEntry } from "@/lib/regime/useVcgSeries";
import { interpretationLabel, regimeBadgeColor, tierColor } from "./format";

/* Signal strip: state badges + the four headline metric cards. */
export default function VcgSignalStrip({
  data,
  sig,
  interpColor,
  lastSync,
  dseries,
}: {
  data: VcgLiveResponse;
  sig: VcgSignal;
  interpColor: string;
  lastSync: VcgLiveResponse["scan_time"];
  dseries: (k: keyof VcgDailyEntry) => (number | null)[];
}) {
  return (
    <div className="section">
      <div className="section-header">
        <div className="section-title">
          <Zap size={14} />
          VCG Signal
          {/* The empirical caveat rides the tooltip because the state names
                  don't carry it: "RISK-OFF" is positioning vocabulary, and a
                  reader will take it as an instruction to cut equity. Tested
                  2007–2026 (n=4,758), armed days match baseline SPX returns —
                  see docs/research/2026-07-29-vcg-spx-forward-returns.md. */}
          <InfoTooltip text="Volatility-Credit Gap: detects divergence between the vol complex (VIX/VVIX) and credit markets (HYG/JNK/LQD). Signals: RISK_OFF (tier 1–2), EDR (early divergence), BOUNCE (counter-signal), NORMAL. These describe coincident vol/credit stress — they do NOT predict SPX direction (2007–2026, n=4,758: armed days match baseline returns). Elevated |z| does associate with higher forward realised volatility." />
        </div>
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: "6px",
            flexWrap: "wrap",
          }}
        >
          {/* Regime badge */}
          <span
            className="pill"
            style={{
              background: regimeBadgeColor(sig.regime),
              color: "#fff",
              fontSize: "9px",
            }}
            data-testid="vcg-regime-badge"
          >
            {sig.regime}
          </span>
          {/* RISK-OFF */}
          {sig.ro === 1 && (
            <span
              className="pill"
              style={{
                background: "var(--fault, var(--negative))",
                color: "#fff",
                fontSize: "9px",
              }}
              data-testid="vcg-ro-badge"
            >
              <AlertTriangle size={10} style={{ marginRight: "3px" }} />
              RISK-OFF
            </span>
          )}
          {/* EDR (only when not already RISK-OFF) */}
          {sig.edr === 1 && sig.ro !== 1 && (
            <span
              className="pill"
              style={{
                background: "var(--warning)",
                color: "#000",
                fontSize: "9px",
                fontWeight: 700,
              }}
              data-testid="vcg-edr-badge"
            >
              EDR
            </span>
          )}
          {/* Tier badge */}
          {sig.tier != null && (
            <span
              className="pill"
              style={{
                background: tierColor(sig.tier),
                color: "#fff",
                fontSize: "9px",
              }}
              data-testid="vcg-tier-badge"
            >
              T{sig.tier}
            </span>
          )}
          {/* Bounce */}
          {sig.bounce === 1 && (
            <span
              className="pill"
              style={{
                background: "var(--signal-core, var(--positive))",
                color: "#000",
                fontSize: "9px",
                fontWeight: 700,
              }}
              data-testid="vcg-bounce-badge"
            >
              <TrendingUp size={10} style={{ marginRight: "3px" }} />
              BOUNCE
            </span>
          )}
          <span
            style={{
              fontFamily: "var(--font-mono)",
              fontSize: "9px",
              color: "var(--text-muted)",
            }}
            data-testid="vcg-proxy"
          >
            {data.credit_proxy}
          </span>
          {lastSync && (
            <span
              style={{
                fontFamily: "var(--font-mono)",
                fontSize: "9px",
                color:
                  data.basis === "live"
                    ? "var(--positive)"
                    : "var(--text-muted)",
              }}
              data-testid="vcg-live-time"
            >
              {data.basis === "live" ? "LIVE · " : ""}
              {new Date(lastSync).toLocaleTimeString("en-US", {
                hour: "numeric",
                minute: "2-digit",
              })}
            </span>
          )}
        </div>
      </div>

      <div className="metrics-grid">
        <div className="metric-card">
          <div className="metric-label">VCG Z-Score</div>
          <div
            className="metric-value"
            style={{ color: interpColor }}
            data-testid="vcg-z-score"
          >
            {formatSignedNumber(sig.vcg)}
          </div>
          <div className="metric-change" style={{ color: interpColor }}>
            {interpretationLabel(sig.interpretation)}
          </div>
          <CardSparkline
            values={dseries("vcg")}
            label="VCG z-score daily, 90d"
            color="var(--accent-warm, #F5A623)"
          />
        </div>
        <div className="metric-card">
          <div className="metric-label">VCG Adj (Panic-Adj)</div>
          <div className="metric-value">{formatSignedNumber(sig.vcg_adj)}</div>
          <div className="metric-change neutral">
            {sig.pi_panic > 0
              ? `π = ${sig.pi_panic.toFixed(2)} (panic-adjustment active)`
              : "π = 0 (no panic adjustment)"}
          </div>
          <CardSparkline
            values={dseries("vcg_adj")}
            label="VCG adjusted daily, 90d"
          />
        </div>
        <div className="metric-card">
          <div className="metric-label">Credit 5d Return</div>
          <div
            className={`metric-value ${
              sig.credit_5d_return_pct >= 0 ? "positive" : "negative"
            }`}
          >
            {formatPercent(sig.credit_5d_return_pct)}
          </div>
          <div className="metric-change neutral">
            {data.credit_proxy} @ ${formatNumber(sig.credit_price)}
          </div>
          <CardSparkline
            values={dseries("credit_5d_return_pct")}
            label="Credit 5d return daily, 90d"
          />
        </div>
        <div className="metric-card">
          <div className="metric-label">Residual</div>
          <div className="metric-value">
            {sig.residual != null ? sig.residual.toFixed(6) : "---"}
          </div>
          <div className="metric-change neutral">MODEL ε</div>
          <CardSparkline
            values={dseries("residual")}
            label="Model residual daily, 90d"
          />
        </div>
      </div>
    </div>
  );
}
